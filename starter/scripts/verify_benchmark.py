"""Verify benchmark/questions.jsonl against the normalized corpus and freeze it.

Checks (any failure exits non-zero):
  - >= 20 questions, unique ids, >= 15 dev / >= 5 test, >= 3 filter questions with >= 1 in test;
  - required fields present;
  - every evidence_quote (and alternative) occurs on its gold page after normalization;
  - evidence that also occurs on a page not declared as gold/alternative is reported;
  - filter keys are allowed, values exist in corpus metadata, and the gold page satisfies them;
  - the question text does not leak the year, law number, law title or source id.
Writes benchmark/verification.json with per-question results and the sha256 of the file.

Run from starter/ after `python -m src.ingestion`:  python scripts/verify_benchmark.py
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import BENCHMARK, MANIFEST, RESULTS  # noqa: E402
from src.ingestion import normalize_text  # noqa: E402

REQUIRED = ["id", "split", "type", "question", "expected_answer", "gold_source_id", "gold_page",
            "evidence_quote", "filter"]
ALLOWED_FILTER_KEYS = {"year"}


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def main() -> None:
    qpath = BENCHMARK / "questions.jsonl"
    questions = [json.loads(l) for l in qpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    pages = [json.loads(l) for l in (RESULTS / "pages.jsonl").read_text(encoding="utf-8").splitlines()]
    page_text = {(p["document_id"], p["page"]): squash(p["text"]) for p in pages}
    page_meta = {(p["document_id"], p["page"]): p["metadata"] for p in pages}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    leak_terms = set()
    for d in manifest["documents"]:
        leak_terms |= {d["source_id"], d["law_number"], str(d["year"]), d["title"]}
    filter_values = {"year": {d["year"] for d in manifest["documents"]}}

    errors, results = [], []
    ids = [q.get("id") for q in questions]
    if len(set(ids)) != len(ids):
        errors.append("duplicate question ids")
    for q in questions:
        r = {"id": q.get("id"), "checks": {}}
        missing = [k for k in REQUIRED if k not in q]
        if missing:
            errors.append(f"{q.get('id')}: missing fields {missing}")
            continue
        golds = [(q["gold_source_id"], q["gold_page"], q["evidence_quote"])] + [
            (a["source_id"], a["page"], a["evidence_quote"]) for a in q.get("alternatives", [])]
        declared = {(s, p) for s, p, _ in golds}
        for s, p, ev in golds:
            key = (s, p)
            if key not in page_text:
                errors.append(f"{q['id']}: gold page {key} not in indexed corpus")
                continue
            found = squash(ev) in page_text[key]
            r["checks"][f"evidence_on_{s}_p{p}"] = found
            if not found:
                errors.append(f"{q['id']}: evidence not found on {s} p{p}")
            elsewhere = [k for k, t in page_text.items() if squash(ev) in t and k not in declared]
            if elsewhere:
                errors.append(f"{q['id']}: evidence also occurs on undeclared pages {elsewhere}")
        if q["filter"]:
            bad_keys = set(q["filter"]) - ALLOWED_FILTER_KEYS
            if bad_keys:
                errors.append(f"{q['id']}: filter keys not allowed {bad_keys}")
            for k, v in q["filter"].items():
                if v not in filter_values.get(k, set()):
                    errors.append(f"{q['id']}: filter value {k}={v} not present in corpus")
                for s, p, _ in golds:
                    if page_meta.get((s, p), {}).get(k) != v:
                        errors.append(f"{q['id']}: gold {s} p{p} does not satisfy filter {k}={v}")
            r["checks"]["filter_valid"] = True
        leaks = [t for t in leak_terms if t.lower() in q["question"].lower()]
        r["checks"]["no_leak_in_question"] = not leaks
        if leaks:
            errors.append(f"{q['id']}: question leaks {leaks}")
        results.append(r)

    dev = [q for q in questions if q["split"] == "dev"]
    test = [q for q in questions if q["split"] == "test"]
    flt = [q for q in questions if q["filter"]]
    counts = {"total": len(questions), "dev": len(dev), "test": len(test), "with_filter": len(flt),
              "with_filter_test": sum(1 for q in flt if q["split"] == "test"),
              "by_type": {t: sum(1 for q in questions if q["type"] == t) for t in sorted({q["type"] for q in questions})},
              "gold_by_document": {s: sum(1 for q in questions if q["gold_source_id"] == s)
                                   for s in sorted({q["gold_source_id"] for q in questions})}}
    if counts["total"] < 20: errors.append("fewer than 20 questions")
    if counts["dev"] < 15: errors.append("fewer than 15 dev questions")
    if counts["test"] < 5: errors.append("fewer than 5 test questions")
    if counts["with_filter"] < 3: errors.append("fewer than 3 filter questions")
    if counts["with_filter_test"] < 1: errors.append("no filter question in test")

    report = {"verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "questions_sha256": hashlib.sha256(qpath.read_bytes()).hexdigest(),
              "counts": counts, "errors": errors, "results": results}
    (BENCHMARK / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("questions_sha256", "counts", "errors")}, ensure_ascii=False, indent=1))
    if errors:
        sys.exit(1)
    print("Benchmark OK")


if __name__ == "__main__":
    main()
