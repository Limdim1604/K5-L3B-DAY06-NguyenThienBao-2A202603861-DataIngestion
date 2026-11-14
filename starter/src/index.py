"""Build (or refresh) the three pgvector indexes A, B and C from the PDF corpus.

A: fixed-size chunks.  B: structure-aware chunks.  C: the same chunks and vectors as B (stored under
strategy 'C'); C differs from B only at query time, where it applies the metadata filter.
Only chunks that are new or whose text changed are embedded; re-running on an unchanged corpus
embeds nothing and writes nothing (the run log proves there is no duplication).

Run from starter/:  python -m src.index
Appends a run record to results/index_log.json.
"""
import json
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from .chunking import chunk_corpus
from .config import RESULTS, STARTER
from .embeddings import MyEmbedder
from .ingestion import load_corpus
from .store import PgVectorStore, text_hash

load_dotenv(STARTER / ".env")


def build_indexes(embedder: MyEmbedder | None = None) -> dict:
    t0 = time.perf_counter()
    pages, ingest_log = load_corpus()
    t_ingest = time.perf_counter() - t0
    embedder = embedder or MyEmbedder()
    store = PgVectorStore(os.environ["DATABASE_URL"], embedder.dimensions)
    store.create_schema()
    documents = sorted({p.document_id for p in pages})
    run = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "embedder": embedder.info(), "store": store.server_info(),
           "ingest_seconds": round(t_ingest, 3), "pages": len(pages), "strategies": {}}

    vectors_by_strategy: dict[str, dict[str, list[float] | None]] = {}
    for strategy in ("A", "B", "C"):
        t = time.perf_counter()
        chunks = chunk_corpus(pages, strategy)
        for c in chunks:
            c.metadata["strategy"] = strategy
        t_chunk = time.perf_counter() - t
        stored = store.existing_hashes(strategy, embedder.model_name)
        todo = [i for i, c in enumerate(chunks) if stored.get(c.chunk_id) != text_hash(c.text)]
        t = time.perf_counter()
        if strategy == "C":  # identical chunks to B -> reuse B's vectors instead of re-embedding
            b_vecs = vectors_by_strategy["B"]
            new_vectors = {i: b_vecs.get(chunks[i].chunk_id) for i in todo}
            missing = [i for i, v in new_vectors.items() if v is None]
            if missing:  # B unchanged in this run but C missing/changed: embed them
                for i, v in zip(missing, embedder.embed_documents([chunks[i].text for i in missing])):
                    new_vectors[i] = v
            embedded = len(missing)
        else:
            new_vectors = dict(zip(todo, embedder.embed_documents([chunks[i].text for i in todo])))
            embedded = len(todo)
        t_embed = time.perf_counter() - t
        vectors = [new_vectors.get(i) for i in range(len(chunks))]
        vectors_by_strategy[strategy] = {c.chunk_id: v for c, v in zip(chunks, vectors) if v is not None}
        t = time.perf_counter()
        result = store.upsert(strategy, chunks, vectors, embedder.model_name, documents)
        t_upsert = time.perf_counter() - t
        run["strategies"][strategy] = {
            "chunks": len(chunks), "embedded": embedded, "reused_from_B": len(todo) - embedded if strategy == "C" else 0,
            **result, "rows_in_store": store.count(strategy), "chunk_seconds": round(t_chunk, 3),
            "embed_seconds": round(t_embed, 3), "upsert_seconds": round(t_upsert, 3), "cost_usd": 0.0}
    run["total_seconds"] = round(time.perf_counter() - t0, 3)
    run["rows_total"] = store.count()
    return run


def main() -> None:
    run = build_indexes()
    log_path = RESULTS / "index_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {"runs": []}
    log["runs"].append(run)
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: run[k] for k in ("embedder", "store", "strategies", "total_seconds", "rows_total")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
