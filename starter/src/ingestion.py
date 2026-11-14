"""Read and normalize the PDF corpus, keeping every page traceable to its source.

Run from starter/:  python -m src.ingestion
Writes results/pages.jsonl (normalized pages + metadata) and results/ingest_log.json.
"""
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .config import MANIFEST, RESULTS, ROOT
from .models import DocumentPage

# Structural line patterns of Vietnamese legal texts.
RE_CHAPTER = re.compile(r"^Chương ([IVXLC]+)\b")
RE_SECTION = re.compile(r"^Mục (\d+)\b")
RE_ARTICLE = re.compile(r"^Điều (\d+)\.\s*(.*)$")
RE_CLAUSE = re.compile(r"^(\d+)\.\s+\S")
RE_POINT = re.compile(r"^([a-zđ])\)\s+\S")
RE_SEPARATOR = re.compile(r"^[-_=.…\s]{3,}$")
SPACE_CHARS = dict.fromkeys(map(ord, "       　\t\f\v"), " ")
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿­"), None)


def _is_caps_title(line: str) -> bool:
    """Chapter/section titles are printed fully upper-case (e.g. 'NHỮNG QUY ĐỊNH CHUNG')."""
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def _starts_block(line: str) -> bool:
    return bool(RE_CHAPTER.match(line) or RE_SECTION.match(line) or RE_ARTICLE.match(line)
                or RE_CLAUSE.match(line) or RE_POINT.match(line) or _is_caps_title(line))


def _clean_line(raw: str) -> str:
    line = unicodedata.normalize("NFC", raw).translate(SPACE_CHARS).translate(ZERO_WIDTH)
    return re.sub(r" {2,}", " ", line).strip()


def normalize_lines(lines: list[tuple[str, bool | None]]) -> str:
    """Join PDF layout lines into logical paragraphs.

    Each input line carries a bold flag (True/False) or None when font information is
    unavailable. A new paragraph starts at a structural marker (Chương, Mục, Điều N.,
    khoản 'N.', điểm 'a)', upper-case title). An article heading ('Điều N. ...') that wraps
    keeps absorbing following lines only while they are bold, so the heading never swallows
    the first body sentence. Without font information a heading is closed after its first line.
    Paragraphs are separated by a single '\n'.
    """
    paragraphs: list[str] = []
    in_heading = False
    for raw, bold in lines:
        line = _clean_line(raw)
        if not line or RE_SEPARATOR.match(line):
            continue
        prev = paragraphs[-1] if paragraphs else None
        if prev is None or _starts_block(line):
            # consecutive upper-case title lines belong to one title
            if prev is not None and _is_caps_title(line) and _is_caps_title(prev) and not RE_CHAPTER.match(prev):
                paragraphs[-1] = f"{prev} {line}"
            else:
                paragraphs.append(line)
            in_heading = bool(RE_ARTICLE.match(line)) and bold is not False
        elif in_heading:
            if bold:
                paragraphs[-1] = f"{prev} {line}"
            else:
                paragraphs.append(line)
                in_heading = False
        else:
            paragraphs[-1] = f"{prev} {line}"
    return "\n".join(paragraphs)


def normalize_text(text: str) -> str:
    """Normalize Unicode (NFC) and whitespace of plain text without font information
    (used for queries, evidence quotes and any non-PDF text)."""
    return normalize_lines([(raw, None) for raw in text.splitlines()])


def _page_lines_with_bold(page) -> list[tuple[str, bool]]:
    """Rebuild the page text from pypdf text runs (identical to extract_text()) and mark a line
    bold when most of its non-space characters were drawn with a bold font."""
    chars: list[tuple[str, bool]] = []

    def visitor(text, cm, tm, font_dict, font_size):
        is_bold = "bold" in str((font_dict or {}).get("/BaseFont", "")).lower()
        chars.extend((c, is_bold) for c in text)

    page.extract_text(visitor_text=visitor)
    lines, current = [], []
    for c, b in chars + [("\n", False)]:
        if c == "\n":
            visible = [bb for cc, bb in current if not cc.isspace()]
            lines.append(("".join(cc for cc, _ in current), bool(visible) and sum(visible) * 2 > len(visible)))
            current = []
        else:
            current.append((c, b))
    return lines


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each physical page with its 1-based page number; empty pages are kept (text='')
    so the caller can log them. OCR is not applied (corpus PDFs have a text layer)."""
    reader = PdfReader(str(path))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        lines = _page_lines_with_bold(page)
        raw_chars = len("\n".join(t for t, _ in lines).strip())
        pages.append(DocumentPage(document_id=document_id, source=source, page=number,
                                  text=normalize_lines(lines),
                                  metadata={"raw_chars": raw_chars, "bold_lines": sum(b for _, b in lines)}))
    return pages


def annotate_structure(pages: list[DocumentPage]) -> None:
    """Record, for every page of one document, the chapter/article in force at the top of the
    page and the articles whose heading appears on it. Values come from the text itself."""
    state: dict[str, Any] = {"chapter": None, "chapter_title": None, "article": None, "article_title": None}
    for page in pages:
        page.metadata["at_page_start"] = dict(state)
        headings = []
        lines = page.text.split("\n")
        for i, line in enumerate(lines):
            if m := RE_CHAPTER.match(line):
                title = lines[i + 1] if i + 1 < len(lines) and _is_caps_title(lines[i + 1]) else None
                state.update(chapter=m.group(1), chapter_title=title)
            elif m := RE_ARTICLE.match(line):
                state.update(article=int(m.group(1)), article_title=m.group(2).strip())
                headings.append(int(m.group(1)))
        page.metadata["articles_on_page"] = headings
        page.metadata["chapters_on_page"] = [RE_CHAPTER.match(l).group(1) for l in lines if RE_CHAPTER.match(l)]


def load_corpus(manifest_path: Path = MANIFEST) -> tuple[list[DocumentPage], dict[str, Any]]:
    """Load every counted page listed in the manifest; return pages and an ingestion log."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages_out: list[DocumentPage] = []
    log: dict[str, Any] = {"documents": [], "errors": [], "empty_pages": [], "excluded_pages": [],
                           "warnings": []}
    started = time.perf_counter()
    for doc in manifest["documents"]:
        path = ROOT / doc["source_path_local"]
        try:
            pages = load_pdf(path, doc["source_id"], doc["source_path_local"])
        except Exception as exc:  # report, never silently skip
            log["errors"].append({"document_id": doc["source_id"], "error": repr(exc)})
            raise
        if len(pages) != doc["physical_pages"]:
            log["warnings"].append(f"{doc['source_id']}: {len(pages)} pages read, manifest says {doc['physical_pages']}")
        annotate_structure(pages)
        counted = set(doc["counted_pages"])
        kept = 0
        for page in pages:
            if not page.text:
                log["empty_pages"].append({"document_id": page.document_id, "page": page.page})
            if page.page not in counted:
                log["excluded_pages"].append({"document_id": page.document_id, "page": page.page,
                                              "reason": next((p.get("exclusion_reason") for p in doc["pages"]
                                                              if p["page"] == page.page), None)})
                continue
            page.metadata.update(year=doc["year"], law_number=doc["law_number"], title=doc["title"],
                                 normalized_chars=len(page.text))
            pages_out.append(page)
            kept += 1
        arts = sorted({a for p in pages for a in p.metadata["articles_on_page"]})
        missing = sorted(set(range(1, max(arts) + 1)) - set(arts)) if arts else []
        if missing:
            log["warnings"].append(f"{doc['source_id']}: article headings not detected: {missing}")
        log["documents"].append({
            "document_id": doc["source_id"], "physical_pages": len(pages), "kept_pages": kept,
            "raw_chars": sum(p.metadata["raw_chars"] for p in pages if p.page in counted),
            "normalized_chars": sum(len(p.text) for p in pages if p.page in counted),
            "articles_detected": len(arts),
            "chapters_detected": sorted({c for p in pages for c in p.metadata["chapters_on_page"]},
                                        key=lambda r: ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"].index(r)),
        })
    log["kept_pages_total"] = len(pages_out)
    log["seconds"] = round(time.perf_counter() - started, 3)
    return pages_out, log


def main() -> None:
    pages, log = load_corpus()
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "pages.jsonl").open("w", encoding="utf-8") as fh:
        for p in pages:
            fh.write(json.dumps({"document_id": p.document_id, "source": p.source, "page": p.page,
                                 "metadata": p.metadata, "text": p.text}, ensure_ascii=False) + "\n")
    (RESULTS / "ingest_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: log[k] for k in ("documents", "empty_pages", "excluded_pages", "warnings",
                                          "errors", "kept_pages_total", "seconds")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
