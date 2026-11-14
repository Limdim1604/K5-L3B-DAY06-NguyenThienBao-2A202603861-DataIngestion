"""PostgreSQL + pgvector store: persistent vectors, metadata columns, cosine search with filters.

One table holds every strategy; (strategy, chunk_id) is the primary key, so re-ingesting the same
corpus updates rows in place instead of duplicating them. Search is exact (sequential scan with the
cosine-distance operator `<=>`, no ANN index) which is cheap at this corpus size and means a
metadata filter can never reduce the number of returned neighbours below top_k.
"""
import hashlib
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk

# user-facing filter key -> SQL column (whitelist; values are always bound as parameters)
FILTER_COLUMNS = {"year": "year", "document_id": "document_id", "chapter": "chapter", "article": "article"}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, table: str = "chunks") -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty; copy starter/.env.example to starter/.env")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive int")
        if not table.isidentifier():
            raise ValueError("invalid table name")
        self.database_url, self.dimensions, self.table = database_url, dimensions, table

    def _connect(self):
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    strategy        text        NOT NULL,
                    chunk_id        text        NOT NULL,
                    document_id     text        NOT NULL,
                    source          text        NOT NULL,
                    page            integer     NOT NULL,
                    year            integer     NOT NULL,
                    law_number      text        NOT NULL,
                    chapter         text,
                    article         integer,
                    text            text        NOT NULL,
                    text_sha256     text        NOT NULL,
                    embedding_model text        NOT NULL,
                    metadata        jsonb       NOT NULL,
                    embedding       vector({self.dimensions}) NOT NULL,
                    updated_at      timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {self.table}_filter_idx ON {self.table} (strategy, year, document_id)")
            # fail loudly if an existing table was created with another dimension
            dim = conn.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'embedding'",
                               (self.table,)).fetchone()[0]
            if dim != self.dimensions:
                raise RuntimeError(f"table {self.table} has vector({dim}), model produces {self.dimensions}")

    def existing_hashes(self, strategy: str, model: str) -> dict[str, str]:
        """chunk_id -> text hash for rows already embedded with `model` (lets callers skip re-embedding)."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT chunk_id, text_sha256 FROM {self.table} WHERE strategy = %s AND embedding_model = %s",
                                (strategy, model)).fetchall()
        return dict(rows)

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float] | None], model: str,
               documents: list[str] | None = None) -> dict[str, int]:
        """Insert new chunks, update changed ones, leave identical ones untouched and delete chunks
        of the given documents that are no longer produced (obsolete after a source change).
        `chunks` must be the complete chunk list for `documents` (default: documents in `chunks`).
        A vector may be None only for a chunk whose stored text hash (same model) is identical."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if any(v is not None and len(v) != self.dimensions for v in vectors):
            raise ValueError(f"vector dimension differs from {self.dimensions}")
        ids = [c.chunk_id for c in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate chunk ids in one upsert")
        documents = sorted(set(documents or [c.document_id for c in chunks]))
        stats = {"inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0}
        stored = self.existing_hashes(strategy, model) if any(v is None for v in vectors) else {}
        with self._connect() as conn:
            for c, v in zip(chunks, vectors):
                if v is None:
                    if stored.get(c.chunk_id) != text_hash(c.text):
                        raise ValueError(f"{c.chunk_id}: no vector given but stored text differs or is missing")
                    stats["unchanged"] += 1
                    continue
                m = c.metadata
                row = conn.execute(f"""
                    INSERT INTO {self.table} AS t (strategy, chunk_id, document_id, source, page, year, law_number,
                        chapter, article, text, text_sha256, embedding_model, metadata, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                        year = EXCLUDED.year, law_number = EXCLUDED.law_number, chapter = EXCLUDED.chapter,
                        article = EXCLUDED.article, text = EXCLUDED.text, text_sha256 = EXCLUDED.text_sha256,
                        embedding_model = EXCLUDED.embedding_model, metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding, updated_at = now()
                    WHERE t.text_sha256 IS DISTINCT FROM EXCLUDED.text_sha256
                       OR t.embedding_model IS DISTINCT FROM EXCLUDED.embedding_model
                       OR t.metadata IS DISTINCT FROM EXCLUDED.metadata
                    RETURNING (xmax = 0) AS inserted""",
                    (strategy, c.chunk_id, c.document_id, c.source, c.page, m["year"], m["law_number"],
                     m.get("chapter"), m.get("article"), c.text, text_hash(c.text), model, Jsonb(m), _vec(v))).fetchone()
                if row is None:
                    stats["unchanged"] += 1
                elif row[0]:
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1
            cur = conn.execute(f"DELETE FROM {self.table} WHERE strategy = %s AND document_id = ANY(%s) AND NOT (chunk_id = ANY(%s))",
                               (strategy, documents, ids))
            stats["deleted"] = cur.rowcount
        return stats

    def count(self, strategy: str | None = None) -> int:
        with self._connect() as conn:
            if strategy is None:
                return conn.execute(f"SELECT count(*) FROM {self.table}").fetchone()[0]
            return conn.execute(f"SELECT count(*) FROM {self.table} WHERE strategy = %s", (strategy,)).fetchone()[0]

    def delete_strategy(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute(f"DELETE FROM {self.table} WHERE strategy = %s", (strategy,)).rowcount

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exact cosine search inside one strategy; optional equality filters on whitelisted columns.
        Returns chunk id, text, cosine similarity score and metadata, best first."""
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector dimension mismatch")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTER_COLUMNS:
                raise ValueError(f"filter key not allowed: {key}")
            where.append(f"{FILTER_COLUMNS[key]} = %s")
            params.append(value)
        qv = _vec(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, year, law_number, chapter, article, text, metadata, "
               f"1 - (embedding <=> %s::vector) AS score FROM {self.table} WHERE {' AND '.join(where)} "
               f"ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [qv, *params, qv, top_k]).fetchall()
        keys = ["chunk_id", "document_id", "source", "page", "year", "law_number", "chapter", "article", "text",
                "metadata", "score"]
        return [dict(zip(keys, r)) | {"rank": i + 1, "score": float(r[-1])} for i, r in enumerate(rows)]

    def server_info(self) -> dict[str, str]:
        with self._connect() as conn:
            pg = conn.execute("SELECT current_setting('server_version')").fetchone()[0]
            ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
        return {"postgresql": pg, "pgvector": ext, "table": self.table, "metric": "cosine (<=>)",
                "search": "exact (no ANN index)"}
