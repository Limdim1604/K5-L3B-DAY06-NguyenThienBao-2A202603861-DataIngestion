"""Build the manual-audit tables and summary from traces + results/manual_labels.json.

- results/manual_audit_coherence.csv : 10 pre-selected positions x A/B/C, score 0-2 + reason
- results/manual_audit_metadata.csv  : 6 test questions x top-3 x A/B/C, automatic cross-checks
                                        against the raw PDF + the manual verdict
- results/manual_audit_grounding.csv : 6 test questions x A/B/C, score 0-2 + reason
- results/manual_audit_summary.json  : averages / counts per strategy (+ filter compliance)
Labels are human judgements stored in manual_labels.json; this script only joins and counts.

Run from starter/:  python scripts/build_audit.py
"""
import csv
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import MANIFEST, RESULTS, ROOT  # noqa: E402

STRATS = ("A", "B", "C")


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def key(t: str) -> str:
    return re.sub(r"[\s\-]+", "", t)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    labels = json.loads((RESULTS / "manual_labels.json").read_text(encoding="utf-8"))
    pages = sorted(load_jsonl(RESULTS / "pages.jsonl"), key=lambda r: (r["document_id"], r["page"]))
    chunks = {s: load_jsonl(RESULTS / f"chunks_{s}.jsonl") for s in ("A", "B")}
    chunks["C"] = chunks["B"]
    summary: dict = {"labeled_by": labels["labeled_by"], "coherence": {}, "metadata": {}, "grounding": {}}

    # ---------------- coherence
    rows = []
    selected = [pages[i] for i in range(0, len(pages), 5)][:10]
    for k, p in enumerate(selected, start=1):
        pid, mid = f"POS{k:02d}", len(p["text"]) // 2
        for s in STRATS:
            c = next(c for c in chunks[s] if c["document_id"] == p["document_id"] and c["page"] == p["page"]
                     and c["metadata"]["char_start"] <= mid < c["metadata"]["char_end"])
            score, reason = labels["coherence"]["labels"][pid]["B" if s == "C" else s]
            rows.append({"position": pid, "document_id": p["document_id"], "page": p["page"], "char_pos": mid,
                         "strategy": s, "chunk_id": c["chunk_id"], "chunk_chars": len(c["text"]),
                         "score_0_2": score, "reason": reason + (" (C = chunk của B)" if s == "C" else ""),
                         "chunk_text": c["text"]})
    write_csv(RESULTS / "manual_audit_coherence.csv", rows)
    for s in STRATS:
        sc = [r["score_0_2"] for r in rows if r["strategy"] == s]
        summary["coherence"][s] = {"n": len(sc), "mean_0_2": round(sum(sc) / len(sc), 2),
                                   "counts": {str(v): sc.count(v) for v in (0, 1, 2)}}

    # ---------------- metadata (test, top-3)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw, docs = {}, {d["source_id"]: d for d in manifest["documents"]}
    for d in manifest["documents"]:
        for i, pg in enumerate(PdfReader(str(ROOT / d["source_path_local"])).pages, start=1):
            raw[(d["source_id"], i)] = pg.extract_text() or ""
    traces = load_jsonl(RESULTS / "traces_test.jsonl")
    rows = []
    md = labels["metadata"]
    for t in traces:
        for h in t["hits"]:
            body = h["text"].split("\n", 1)[1] if h["metadata"].get("context_prefix") else h["text"]
            d = docs[h["document_id"]]
            verdict = md["exceptions"].get(f"{t['strategy']}|{t['id']}|{h['rank']}", md["default"])
            rows.append({
                "strategy": t["strategy"], "question": t["id"], "rank": h["rank"], "chunk_id": h["chunk_id"],
                "document_id": h["document_id"], "source": h["source"], "page": h["page"], "year": h["year"],
                "law_number": h["law_number"], "chapter": h["chapter"], "article": h["article"],
                "fields_present": all(h.get(k) not in (None, "") for k in ("document_id", "source", "page", "year")),
                "auto_text_on_pdf_page": key(body) in key(raw[(h["document_id"], h["page"])]),
                "auto_source_matches_doc": h["source"] == d["source_path_local"],
                "auto_year_law_match": h["year"] == d["year"] and h["law_number"] == d["law_number"],
                "filter": json.dumps(t["filter"], ensure_ascii=False) if t["filter"] else "",
                "satisfies_filter": "" if not t["filter"] else all(h.get(k) == v for k, v in t["filter"].items()),
                "manual_complete_and_correct": verdict["correct"], "note": verdict["note"]})
    write_csv(RESULTS / "manual_audit_metadata.csv", rows)
    for s in STRATS:
        rs = [r for r in rows if r["strategy"] == s]
        flt = [t for t in traces if t["strategy"] == s and t["filter"]]
        summary["metadata"][s] = {
            "complete_and_correct": f"{sum(r['manual_complete_and_correct'] and r['fields_present'] for r in rs)}/{len(rs)}",
            "auto_text_on_pdf_page": f"{sum(r['auto_text_on_pdf_page'] for r in rs)}/{len(rs)}",
            "filter_compliance_test": (f"{sum(bool(t['filter_compliant_top3']) for t in flt)}/{len(flt)}" if flt else "N/A")}

    # ---------------- grounding (test)
    rows = []
    for t in traces:
        lab = labels["grounding"]["labels"][t["id"]][t["strategy"]]
        rows.append({"strategy": t["strategy"], "question": t["id"], "split": t["split"],
                     "filter_applied": json.dumps(t["filter_applied"], ensure_ascii=False) if t["filter_applied"] else "",
                     "top3": " | ".join(h["chunk_id"] for h in t["hits"]), "auto_evidence_hit_at_3": t["hit_at_3"],
                     "score_0_2": lab[0], "out_of_scope_in_top3": len(lab) > 2 and lab[2] == "out_of_scope",
                     "reason": lab[1]})
    write_csv(RESULTS / "manual_audit_grounding.csv", rows)
    for s in STRATS:
        sc = [r["score_0_2"] for r in rows if r["strategy"] == s]
        summary["grounding"][s] = {"n": len(sc), "mean_0_2": round(sum(sc) / len(sc), 2),
                                   "counts": {str(v): sc.count(v) for v in (0, 1, 2)},
                                   "out_of_scope_in_top3": sum(r["out_of_scope_in_top3"] for r in rows if r["strategy"] == s),
                                   "auto_hit3_vs_manual_disagree": [r["question"] for r in rows if r["strategy"] == s
                                                                    and r["auto_evidence_hit_at_3"] != (r["score_0_2"] == 2)]}
    (RESULTS / "manual_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
