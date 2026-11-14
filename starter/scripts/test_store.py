"""Evidence that the store re-ingests without duplicates, handles changed documents and filters.

1. Re-ingest test on a throw-away table `chunks_reingest_test` (dropped at the end):
   ingest one document's B chunks -> re-ingest unchanged -> re-ingest a "new version" with one chunk
   edited, one removed and one added -> check inserted/updated/unchanged/deleted and row counts.
2. Filter test on the real `chunks` table (strategy C): the same query with year=2015 / year=2018
   must only return rows of that year; an unknown filter key must be rejected.

Run from starter/ after `python -m src.index`:  python scripts/test_store.py
Writes results/store_test.json.
"""
import copy
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.chunking import chunk_corpus  # noqa: E402
from src.config import RESULTS, STARTER  # noqa: E402
from src.embeddings import MyEmbedder  # noqa: E402
from src.ingestion import load_corpus  # noqa: E402
from src.store import PgVectorStore  # noqa: E402

load_dotenv(STARTER / ".env")
URL = os.environ["DATABASE_URL"]
TEST_TABLE = "chunks_reingest_test"


def check(cond: bool, msg: str, log: list) -> None:
    log.append({"check": msg, "passed": bool(cond)})
    print(("PASS " if cond else "FAIL ") + msg)


def main() -> None:
    log: list = []
    embedder = MyEmbedder()
    pages, _ = load_corpus()
    doc_pages = [p for p in pages if p.document_id == "attt-2015"]
    chunks = chunk_corpus(doc_pages, "B")

    store = PgVectorStore(URL, embedder.dimensions, table=TEST_TABLE)
    store.create_schema()
    store.delete_strategy("T")
    try:
        r1 = store.upsert("T", chunks, embedder.embed_documents([c.text for c in chunks]), embedder.model_name)
        check(r1["inserted"] == len(chunks) and store.count("T") == len(chunks), f"first ingest {r1}", log)

        r2 = store.upsert("T", chunks, [None] * len(chunks), embedder.model_name)
        check(r2 == {"inserted": 0, "updated": 0, "unchanged": len(chunks), "deleted": 0}
              and store.count("T") == len(chunks), f"unchanged re-ingest {r2}", log)

        v2 = copy.deepcopy(chunks)
        v2[0].text += " (văn bản sửa đổi giả lập)"           # edited chunk
        removed = v2.pop(5).chunk_id                          # chunk that disappears in the new version
        added = copy.deepcopy(v2[-1])
        added.chunk_id, added.text = added.chunk_id + "-new", added.text + " (đoạn bổ sung giả lập)"
        v2.append(added)                                      # brand-new chunk
        vecs = [embedder.embed_documents([c.text])[0] if i in (0, len(v2) - 1) else None for i, c in enumerate(v2)]
        r3 = store.upsert("T", v2, vecs, embedder.model_name, documents=["attt-2015"])
        check(r3 == {"inserted": 1, "updated": 1, "unchanged": len(v2) - 2, "deleted": 1}
              and store.count("T") == len(v2), f"changed document re-ingest {r3}", log)
        with psycopg.connect(URL) as conn:
            gone = conn.execute(f"SELECT count(*) FROM {TEST_TABLE} WHERE chunk_id = %s", (removed,)).fetchone()[0]
        check(gone == 0, f"obsolete chunk {removed} removed", log)
    finally:
        with psycopg.connect(URL) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {TEST_TABLE}")

    real = PgVectorStore(URL, embedder.dimensions)
    q = embedder.embed_query("Luật có hiệu lực thi hành từ ngày nào?")
    unfiltered = real.search("C", q, 3)
    by_year = {y: real.search("C", q, 3, {"year": y}) for y in (2015, 2018)}
    for y, hits in by_year.items():
        check(len(hits) == 3 and all(h["year"] == y for h in hits), f"filter year={y} returns only {y}", log)
    try:
        real.search("C", q, 3, {"text; DROP TABLE chunks": 1})
        check(False, "unknown filter key rejected", log)
    except ValueError:
        check(True, "unknown filter key rejected", log)
    sample = {"query": "Luật có hiệu lực thi hành từ ngày nào?",
              "unfiltered": [(h["chunk_id"], round(h["score"], 4)) for h in unfiltered],
              **{f"year_{y}": [(h["chunk_id"], round(h["score"], 4)) for h in hits] for y, hits in by_year.items()}}
    print(json.dumps(sample, ensure_ascii=False, indent=1))
    (RESULTS / "store_test.json").write_text(json.dumps({"checks": log, "search_sample": sample},
                                                        ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(c["passed"] for c in log):
        sys.exit(1)


if __name__ == "__main__":
    main()
