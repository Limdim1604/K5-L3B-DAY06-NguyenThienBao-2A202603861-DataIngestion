"""Fixed-size (strategy A) and structure-aware (strategy B) chunking.

Chunks never cross a page boundary, so every chunk maps to exactly one PDF page.
Both strategies attach the same metadata fields (document/page/year/law and the
chapter/article in force at the chunk start), so A-B differs only in how text is cut.

Run from starter/ after `python -m src.ingestion`:  python -m src.chunking
Writes results/chunks_A.jsonl, results/chunks_B.jsonl and results/chunk_stats.json.
"""
import json
import re
import statistics
from typing import Any

from .config import RESULTS
from .ingestion import RE_ARTICLE, RE_CHAPTER, RE_CLAUSE
from .models import Chunk, DocumentPage

FIXED_SIZE, FIXED_OVERLAP = 500, 50
PARAGRAPH_MAX = 1000
DROPPED_HEADING_ONLY: list[str] = []  # filled by by_paragraph, reported in chunk_stats.json


# ---------------------------------------------------------------- structure helpers
def _headings(page: DocumentPage) -> list[tuple[int, str, Any, str | None]]:
    """(char offset, kind, value, title) of every chapter/article heading on the page."""
    out, offset = [], 0
    for line in page.text.split("\n"):
        if m := RE_CHAPTER.match(line):
            out.append((offset, "chapter", m.group(1), None))
        elif m := RE_ARTICLE.match(line):
            out.append((offset, "article", int(m.group(1)), m.group(2).strip()))
        offset += len(line) + 1
    return out


def _structure_meta(page: DocumentPage, start: int, end: int) -> dict[str, Any]:
    """Chapter/article in force at `start`, plus every article overlapping [start, end)."""
    s = page.metadata.get("at_page_start", {})
    chapter, article, title = s.get("chapter"), s.get("article"), s.get("article_title")
    covered = []
    for off, kind, value, t in _headings(page):
        if off <= start:
            if kind == "chapter":
                chapter = value
            else:
                article, title = value, t
        elif off < end and kind == "article":
            covered.append(value)
    return {"chapter": chapter, "article": article, "article_title": title,
            "articles": ([article] if article is not None else []) + covered}


def _base_meta(page: DocumentPage, strategy: str, start: int, end: int, text: str) -> dict[str, Any]:
    return {"year": page.metadata["year"], "law_number": page.metadata["law_number"],
            "title": page.metadata["title"], "strategy": strategy,
            "char_start": start, "char_end": end, "n_chars": len(text),
            **_structure_meta(page, start, end)}


def _chunk(page: DocumentPage, idx: int, text: str, meta: dict[str, Any]) -> Chunk:
    return Chunk(chunk_id=f"{page.document_id}-p{page.page:02d}-{idx:03d}", document_id=page.document_id,
                 source=page.source, page=page.page, text=text, metadata=meta)


# ---------------------------------------------------------------- strategy A
def fixed_size(page: DocumentPage, size: int = FIXED_SIZE, overlap: int = FIXED_OVERLAP) -> list[Chunk]:
    """Sliding windows of at most `size` characters with `overlap` characters shared.
    The window end is moved back to the last whitespace in its final 20% so words are not cut;
    the next window starts `overlap` characters before that end (snapped to a word start)."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")
    text, chunks, start = page.text, [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind(" ", start + int(size * 0.8), end), text.rfind("\n", start + int(size * 0.8), end))
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            lead = len(text[start:end]) - len(text[start:end].lstrip())
            s, e = start + lead, start + lead + len(piece)
            chunks.append(_chunk(page, len(chunks), piece, _base_meta(page, "A", s, e, piece)))
        if end >= len(text):
            break
        nxt = max(end - overlap, start + 1)
        while 0 < nxt < end and not text[nxt - 1].isspace():  # snap to word start
            nxt -= 1
        start = nxt if nxt > start else end
    return chunks


# ---------------------------------------------------------------- strategy B
def _split_long(text: str, max_size: int) -> list[str]:
    """Split one over-long paragraph at sentence/semicolon boundaries, then at spaces."""
    parts, buf = [], ""
    for piece in re.split(r"(?<=[.;:])\s+", text):
        while len(piece) > max_size:
            cut = piece.rfind(" ", 0, max_size)
            cut = cut if cut > 0 else max_size
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(piece[:cut])
            piece = piece[cut:].strip()
        if buf and len(buf) + 1 + len(piece) > max_size:
            parts.append(buf)
            buf = piece
        else:
            buf = f"{buf} {piece}".strip()
    if buf:
        parts.append(buf)
    return parts


def by_paragraph(page: DocumentPage, max_size: int = PARAGRAPH_MAX) -> list[Chunk]:
    """Structure-aware chunks: a new group starts at every chapter or article heading; inside an
    article a clause ('N.') stays together with its points ('a)', 'b)', ...) when it fits.
    Blocks are packed greedily up to `max_size` characters. A chunk that continues an article
    started earlier (on this or a previous page) gets the line 'Điều N. <title> (tiếp)' prepended
    so it remains understandable on its own; char_start/char_end refer to the page text only."""
    lines = page.text.split("\n")
    offsets, off = [], 0
    for line in lines:
        offsets.append(off)
        off += len(line) + 1

    # 1) groups of blocks; a block is a list of line indexes that should stay together
    groups: list[list[list[int]]] = [[]]
    for i, line in enumerate(lines):
        if RE_CHAPTER.match(line) or RE_ARTICLE.match(line):
            if groups[-1]:
                groups.append([])
            groups[-1].append([i])
        elif RE_CLAUSE.match(line) or not groups[-1]:
            groups[-1].append([i])
        else:  # points and plain paragraphs attach to the current block
            groups[-1][-1].append(i)
    # a chapter heading + title line belongs with the article that follows it
    merged: list[list[list[int]]] = []
    for g in groups:
        if merged and all(RE_CHAPTER.match(lines[b[0]]) or lines[b[0]].isupper() for b in merged[-1]):
            merged[-1].extend(g)
        else:
            merged.append(g)

    chunks: list[Chunk] = []

    def is_heading(line: str) -> bool:
        return bool(RE_CHAPTER.match(line) or RE_ARTICLE.match(line) or line.isupper())

    def emit(line_ids: list[int], text: str | None = None) -> None:
        if not line_ids:
            return
        if text is None and all(is_heading(lines[i]) for i in line_ids):
            # heading stranded at the bottom of a page: its body is on the next page, whose
            # first chunk gets 'Điều N. ... (tiếp)' prepended, so nothing is lost by skipping it
            DROPPED_HEADING_ONLY.append(f"{page.document_id}-p{page.page:02d}: "
                                        + " | ".join(lines[i] for i in line_ids)[:120])
            return
        body = text if text is not None else "\n".join(lines[i] for i in line_ids)
        start = offsets[line_ids[0]]
        end = offsets[line_ids[-1]] + len(lines[line_ids[-1]])
        meta = _base_meta(page, "B", start, end, body)
        # first line that is not a chapter heading / upper-case chapter title
        first = next((lines[i] for i in line_ids if not (RE_CHAPTER.match(lines[i]) or lines[i].isupper())), "")
        starts_with_heading = text is None and bool(RE_ARTICLE.match(first))
        if not starts_with_heading and meta["article"] is not None:
            body = f"Điều {meta['article']}. {meta['article_title']} (tiếp)\n{body}"
            meta["context_prefix"] = True
        else:
            meta["context_prefix"] = False
        meta["n_chars"] = len(body)
        chunks.append(_chunk(page, len(chunks), body, meta))

    for group in merged:
        current: list[int] = []
        size = 0
        for block in group:
            block_len = sum(len(lines[i]) + 1 for i in block)
            if current and size + block_len > max_size:
                emit(current)
                current, size = [], 0
            if block_len <= max_size:
                current += block
                size += block_len
                continue
            # block too large: pack its paragraphs; split any single over-long paragraph
            for i in block:
                plen = len(lines[i]) + 1
                if current and size + plen > max_size:
                    emit(current)
                    current, size = [], 0
                if plen <= max_size:
                    current.append(i)
                    size += plen
                else:
                    for part in _split_long(lines[i], max_size):
                        emit([i], part)
        emit(current)
    return chunks


# ---------------------------------------------------------------- export + stats
def chunk_corpus(pages: list[DocumentPage], strategy: str) -> list[Chunk]:
    if strategy == "A":
        return [c for p in pages for c in fixed_size(p)]
    if strategy in ("B", "C"):
        return [c for p in pages for c in by_paragraph(p)]
    raise ValueError(strategy)


def stats(chunks: list[Chunk]) -> dict[str, Any]:
    lens = sorted(len(c.text) for c in chunks)
    return {"chunks": len(chunks), "total_chars": sum(lens), "mean_chars": round(statistics.mean(lens), 1),
            "min": lens[0], "p50": lens[len(lens) // 2], "p95": lens[int(0.95 * (len(lens) - 1))], "max": lens[-1],
            "with_context_prefix": sum(1 for c in chunks if c.metadata.get("context_prefix"))}


def load_pages() -> list[DocumentPage]:
    rows = [json.loads(l) for l in (RESULTS / "pages.jsonl").read_text(encoding="utf-8").splitlines()]
    return [DocumentPage(r["document_id"], r["source"], r["page"], r["text"], r["metadata"]) for r in rows]


def main() -> None:
    pages = load_pages()
    out = {"params": {"A": {"size": FIXED_SIZE, "overlap": FIXED_OVERLAP},
                      "B": {"max_size": PARAGRAPH_MAX, "unit": "article > clause+points > paragraph"}}}
    for strategy in ("A", "B"):
        chunks = chunk_corpus(pages, strategy)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "duplicate chunk ids"
        with (RESULTS / f"chunks_{strategy}.jsonl").open("w", encoding="utf-8") as fh:
            for c in chunks:
                fh.write(json.dumps(c.__dict__, ensure_ascii=False) + "\n")
        out[strategy] = stats(chunks)
    out["B"]["dropped_heading_only"] = sorted(set(DROPPED_HEADING_ONLY))
    (RESULTS / "chunk_stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
