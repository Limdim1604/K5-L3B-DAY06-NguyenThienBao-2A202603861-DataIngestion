"""Automatic retrieval scoring and per-query traces.

A retrieved chunk is a *hit* when it comes from the gold source and gold page (or a declared
alternative) AND contains the whole evidence quote after normalization (NFC + collapsed whitespace).
Hit@1 = questions whose rank-1 chunk is a hit / questions; Evidence Hit@3 = questions with at least
one hit in the top 3 / questions. Coherence and grounding are NOT inferred here: they are labelled
manually (see results/manual_audit_*.csv).
"""
import re
from typing import Any

from .ingestion import normalize_text


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def _golds(question: dict[str, Any]) -> list[tuple[str, int, str]]:
    return [(question["gold_source_id"], int(question["gold_page"]), question["evidence_quote"])] + [
        (a["source_id"], int(a["page"]), a["evidence_quote"]) for a in question.get("alternatives", [])]


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Label each retrieved chunk and compute hit@1 / hit@3 for one question."""
    golds = _golds(question)
    labelled = []
    for h in hits:
        text = squash(h["text"])
        on_gold_page = any(h["document_id"] == s and int(h["page"]) == p for s, p, _ in golds)
        has_evidence = any(h["document_id"] == s and int(h["page"]) == p and squash(ev) in text for s, p, ev in golds)
        filt = question.get("filter") or {}
        labelled.append({**h, "on_gold_page": on_gold_page, "contains_evidence": has_evidence,
                         "is_hit": has_evidence,
                         "satisfies_filter": all(h.get(k) == v for k, v in filt.items()) if filt else None})
    return {
        "hit_at_1": bool(labelled and labelled[0]["is_hit"]),
        "hit_at_3": any(h["is_hit"] for h in labelled[:3]),
        "gold_page_at_3": any(h["on_gold_page"] for h in labelled[:3]),
        "first_hit_rank": next((h["rank"] for h in labelled if h["is_hit"]), None),
        "filter_compliant_top3": all(h["satisfies_filter"] for h in labelled[:3]) if question.get("filter") else None,
        "hits": labelled,
    }


def _frac(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "N": d, "rate": round(n / d, 4) if d else None, "display": f"{n}/{d}"}


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Hit@1, Evidence Hit@3 (and diagnostics) per strategy and split, as n/N."""
    out: dict[str, Any] = {}
    for strategy in sorted({t["strategy"] for t in traces}):
        out[strategy] = {}
        for split in ("dev", "test", "all"):
            rows = [t for t in traces if t["strategy"] == strategy and (split == "all" or t["split"] == split)]
            if not rows:
                continue
            flt = [t for t in rows if t["filter"]]
            out[strategy][split] = {
                "hit_at_1": _frac(sum(t["hit_at_1"] for t in rows), len(rows)),
                "evidence_hit_at_3": _frac(sum(t["hit_at_3"] for t in rows), len(rows)),
                "gold_page_at_3": _frac(sum(t["gold_page_at_3"] for t in rows), len(rows)),
                "filter_questions_hit_at_3": _frac(sum(t["hit_at_3"] for t in flt), len(flt)) if flt else "N/A",
                "filter_compliance_top3": _frac(sum(bool(t["filter_compliant_top3"]) for t in flt), len(flt)) if flt else "N/A",
                "mean_query_ms": round(sum(t["search_ms"] for t in rows) / len(rows), 2),
            }
    return out
