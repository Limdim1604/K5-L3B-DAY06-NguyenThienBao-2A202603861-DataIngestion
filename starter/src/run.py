"""Day 06 pipeline entry point: retrieval benchmark with a dev -> selection -> test protocol.

  python -m src.index              # (once) build/refresh indexes A, B, C in pgvector
  python -m src.run --phase dev    # run A/B/C on dev, select a strategy with the pre-registered rule
  python -m src.run --phase test   # run A/B/C on test with the selection frozen; final metrics

Strategy C applies the question's metadata filter only when the question has one; for all
other questions C runs unfiltered (recorded as filter_applied=false in the trace).
Outputs (results/): traces_<phase>.jsonl, metrics_<phase>.json, selection.json, metrics.json.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from .config import BENCHMARK, RESULTS, STARTER
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .store import PgVectorStore

load_dotenv(STARTER / ".env")
STRATEGIES = ("A", "B", "C")
TOP_K = 3
TIE_TOLERANCE = 1  # questions; pre-registered in benchmark/README.md
SIMPLICITY_ORDER = ["A", "B", "C"]


def load_questions() -> tuple[list[dict[str, Any]], str]:
    path = BENCHMARK / "questions.jsonl"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    verified = json.loads((BENCHMARK / "verification.json").read_text(encoding="utf-8"))
    if verified["questions_sha256"] != sha or verified["errors"]:
        sys.exit("questions.jsonl changed since verification or verification failed; run scripts/verify_benchmark.py")
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()], sha


def run_phase(phase: str, questions: list[dict[str, Any]], embedder: MyEmbedder,
              store: PgVectorStore) -> list[dict[str, Any]]:
    traces = []
    for q in [q for q in questions if q["split"] == phase]:
        t = time.perf_counter()
        qvec = embedder.embed_query(q["question"])  # one query vector shared by all strategies
        embed_ms = (time.perf_counter() - t) * 1000
        for strategy in STRATEGIES:
            filters = q["filter"] if (strategy == "C" and q["filter"]) else None
            t = time.perf_counter()
            hits = store.search(strategy, qvec, TOP_K, filters)
            search_ms = (time.perf_counter() - t) * 1000
            result = evaluate_query(q, hits)
            for h in result["hits"]:
                h["metadata"] = {k: h["metadata"].get(k) for k in
                                 ("law_number", "title", "chapter", "article", "article_title", "articles",
                                  "char_start", "char_end", "n_chars", "context_prefix") if k in h["metadata"]}
            traces.append({
                "id": q["id"], "split": q["split"], "type": q["type"], "strategy": strategy,
                "question": q["question"], "filter": q["filter"], "filter_applied": filters,
                "gold_source_id": q["gold_source_id"], "gold_page": q["gold_page"],
                "evidence_quote": q["evidence_quote"], "expected_answer": q["expected_answer"],
                "query_embed_ms": round(embed_ms, 2), "search_ms": round(search_ms, 2), **result})
    return traces


def select_strategy(metrics: dict[str, Any], chunk_counts: dict[str, int]) -> dict[str, Any]:
    """Pre-registered rule on dev: Hit@3 -> Hit@1 -> filter-question Hit@3 -> filter compliance ->
    fewer chunks, a difference <= TIE_TOLERANCE questions counting as a tie; remaining ties are
    broken by the raw values in the same order, then by simplicity (A, B, C)."""
    def val(s: str, key: str) -> float:
        if key == "chunks":
            return -chunk_counts[s]
        v = metrics[s]["dev"][key]
        return v["n"] if isinstance(v, dict) else 0

    keys = ["evidence_hit_at_3", "hit_at_1", "filter_questions_hit_at_3", "filter_compliance_top3", "chunks"]
    candidates, steps = list(STRATEGIES), []
    for key in keys:
        best = max(val(s, key) for s in candidates)
        tol = 0 if key == "chunks" else TIE_TOLERANCE
        kept = [s for s in candidates if best - val(s, key) <= tol]
        steps.append({"criterion": key, "values": {s: val(s, key) for s in candidates}, "kept": kept})
        candidates = kept
        if len(candidates) == 1:
            break
    if len(candidates) > 1:  # raw tie-break, no tolerance
        for key in keys:
            best = max(val(s, key) for s in candidates)
            candidates = [s for s in candidates if val(s, key) == best]
            steps.append({"criterion": f"raw:{key}", "kept": candidates})
            if len(candidates) == 1:
                break
    if len(candidates) > 1:
        candidates = sorted(candidates, key=SIMPLICITY_ORDER.index)[:1]
        steps.append({"criterion": "simplicity", "kept": candidates})
    return {"selected": candidates[0], "steps": steps}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["dev", "test"], required=True)
    args = parser.parse_args()
    questions, sha = load_questions()
    selection_path = RESULTS / "selection.json"
    if args.phase == "test" and not selection_path.exists():
        sys.exit("Run --phase dev first: the strategy must be selected on dev before test is evaluated.")

    embedder = MyEmbedder()
    store = PgVectorStore(os.environ["DATABASE_URL"], embedder.dimensions)
    chunk_counts = {s: store.count(s) for s in STRATEGIES}
    if not all(chunk_counts.values()):
        sys.exit(f"Empty index {chunk_counts}; run python -m src.index first.")

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    traces = run_phase(args.phase, questions, embedder, store)
    with (RESULTS / f"traces_{args.phase}.jsonl").open("w", encoding="utf-8") as fh:
        for t in traces:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    metrics = summarize(traces)
    run_info = {"phase": args.phase, "run_at": started, "questions_sha256": sha, "top_k": TOP_K,
                "embedder": embedder.info(), "store": store.server_info(), "chunk_counts": chunk_counts}
    (RESULTS / f"metrics_{args.phase}.json").write_text(
        json.dumps({"run": run_info, "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.phase == "dev":
        sel = select_strategy(metrics, chunk_counts)
        sel.update(selected_at=started, questions_sha256=sha, based_on="dev only",
                   rule="see benchmark/README.md 'Tiêu chí chọn cấu hình'")
        if selection_path.exists():
            old = json.loads(selection_path.read_text(encoding="utf-8"))
            if old.get("test_evaluated"):
                sys.exit("Test was already evaluated with a frozen selection; refusing to overwrite it.")
        selection_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Selected on dev: {sel['selected']}")
    else:
        sel = json.loads(selection_path.read_text(encoding="utf-8"))
        sel["test_evaluated"] = started
        selection_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
        dev = json.loads((RESULTS / "metrics_dev.json").read_text(encoding="utf-8"))
        combined = {s: {"dev": dev["metrics"][s]["dev"], "test": metrics[s]["test"]} for s in STRATEGIES}
        (RESULTS / "metrics.json").write_text(json.dumps(
            {"selected_on_dev": sel["selected"], "chunk_counts": chunk_counts, "metrics": combined,
             "dev_run": dev["run"], "test_run": run_info}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Frozen selection: {sel['selected']}")
    for s in STRATEGIES:
        m = metrics[s][args.phase]
        print(f"{s} {args.phase}: Hit@1 {m['hit_at_1']['display']}  Hit@3 {m['evidence_hit_at_3']['display']}  "
              f"filter Hit@3 {m['filter_questions_hit_at_3'] if isinstance(m['filter_questions_hit_at_3'], str) else m['filter_questions_hit_at_3']['display']}  "
              f"compliance {m['filter_compliance_top3'] if isinstance(m['filter_compliance_top3'], str) else m['filter_compliance_top3']['display']}")


if __name__ == "__main__":
    main()
