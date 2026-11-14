"""Re-score existing traces after a gold (evidence) revision, without re-running retrieval.

Retrieval results do not depend on the gold labels (same questions, same query vectors, exact
search), so the stored top-3 of results/traces_{dev,test}.jsonl are re-labelled with the current
benchmark/questions.jsonl. The script:
  - checks benchmark/verification.json matches the current questions file;
  - re-runs evaluate_query on every stored top-3 and reports every label that changed;
  - rewrites traces + metrics files with the new labels and the new questions hash;
  - re-applies the pre-registered selection rule on dev and fails if the selection would change.
Writes results/rescore_log.json.

Run from starter/:  python scripts/rescore_traces.py
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import BENCHMARK, RESULTS  # noqa: E402
from src.evaluation import evaluate_query, summarize  # noqa: E402
from src.run import select_strategy, STRATEGIES  # noqa: E402

LABEL_KEYS = {"on_gold_page", "contains_evidence", "is_hit", "satisfies_filter"}
TRACE_LABELS = ("hit_at_1", "hit_at_3", "gold_page_at_3", "first_hit_rank", "filter_compliant_top3")


def main() -> None:
    qpath = BENCHMARK / "questions.jsonl"
    sha = hashlib.sha256(qpath.read_bytes()).hexdigest()
    ver = json.loads((BENCHMARK / "verification.json").read_text(encoding="utf-8"))
    if ver["questions_sha256"] != sha or ver["errors"]:
        sys.exit("Run scripts/verify_benchmark.py first.")
    questions = {q["id"]: q for q in map(json.loads, qpath.read_text(encoding="utf-8").splitlines()) if q}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log = {"rescored_at": now, "questions_sha256": sha, "retrieval_rerun": False, "changes": [], "phases": {}}

    combined = {}
    for phase in ("dev", "test"):
        tpath, mpath = RESULTS / f"traces_{phase}.jsonl", RESULTS / f"metrics_{phase}.json"
        traces = [json.loads(l) for l in tpath.read_text(encoding="utf-8").splitlines() if l.strip()]
        old_metrics = json.loads(mpath.read_text(encoding="utf-8"))
        new_traces = []
        for t in traces:
            q = questions[t["id"]]
            hits = [{k: v for k, v in h.items() if k not in LABEL_KEYS} for h in t["hits"]]
            res = evaluate_query(q, hits)
            for key in TRACE_LABELS:
                if res[key] != t[key]:
                    log["changes"].append({"phase": phase, "id": t["id"], "strategy": t["strategy"],
                                           "field": key, "old": t[key], "new": res[key]})
            for old_h, new_h in zip(t["hits"], res["hits"]):
                if old_h["is_hit"] != new_h["is_hit"]:
                    log["changes"].append({"phase": phase, "id": t["id"], "strategy": t["strategy"],
                                           "field": f"rank{new_h['rank']}.is_hit", "old": old_h["is_hit"],
                                           "new": new_h["is_hit"]})
            new_traces.append({**t, **res, "evidence_quote": q["evidence_quote"],
                               "expected_answer": q["expected_answer"], "rescored_at": now})
        metrics = summarize(new_traces)
        tpath.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in new_traces), encoding="utf-8")
        run = {**old_metrics["run"], "rescored_at": now, "questions_sha256_at_retrieval": old_metrics["run"]["questions_sha256"],
               "questions_sha256": sha}
        mpath.write_text(json.dumps({"run": run, "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")
        log["phases"][phase] = {s: {k: metrics[s][phase][k] for k in ("hit_at_1", "evidence_hit_at_3")} for s in STRATEGIES}
        log["phases"][phase + "_metrics_identical_to_before"] = (
            json.dumps({s: {k: v for k, v in metrics[s][phase].items() if k != "mean_query_ms"} for s in STRATEGIES}, sort_keys=True)
            == json.dumps({s: {k: v for k, v in old_metrics["metrics"][s][phase].items() if k != "mean_query_ms"} for s in STRATEGIES}, sort_keys=True))
        combined[phase] = (metrics, run)

    selection = json.loads((RESULTS / "selection.json").read_text(encoding="utf-8"))
    chunk_counts = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))["chunk_counts"]
    re_sel = select_strategy(combined["dev"][0], chunk_counts)
    log["selection_unchanged"] = re_sel["selected"] == selection["selected"]
    if not log["selection_unchanged"]:
        sys.exit(f"Selection would change ({selection['selected']} -> {re_sel['selected']}); report this explicitly.")
    selection["gold_revision"] = {"at": now, "questions_sha256": sha, "reselected_on_dev": re_sel["selected"],
                                  "note": "q09/q13 evidence widened after evaluation; selection re-checked on dev, unchanged"}
    (RESULTS / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    m = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))
    m["metrics"] = {s: {"dev": combined["dev"][0][s]["dev"], "test": combined["test"][0][s]["test"]} for s in STRATEGIES}
    m["dev_run"], m["test_run"] = combined["dev"][1], combined["test"][1]
    m["gold_revision"] = log["rescored_at"]
    (RESULTS / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "rescore_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: log[k] for k in ("changes", "selection_unchanged")} |
                     {k: v for k, v in log["phases"].items() if k.endswith("identical_to_before")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
