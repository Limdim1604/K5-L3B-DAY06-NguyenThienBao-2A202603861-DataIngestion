"""Real embedding provider: intfloat/multilingual-e5-base run locally with sentence-transformers.

Per the model card, E5 expects the prefix 'query: ' on questions and 'passage: ' on documents;
vectors are L2-normalized so cosine similarity equals the dot product. If the model cannot be
loaded the error propagates: there is no fallback to mock or random vectors.
"""
import os
from typing import Protocol

DEFAULT_MODEL = "intfloat/multilingual-e5-base"


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """sentence-transformers adapter for E5 models (local, no API key, cost 0)."""

    def __init__(self, model_name: str | None = None, batch_size: int = 32, device: str | None = None) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.batch_size = batch_size
        self._model = SentenceTransformer(self.model_name, device=self.device)
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dimensions = int(get_dim())
        self.max_seq_length = int(self._model.max_seq_length)
        self.revision = self._cached_revision()

    def _cached_revision(self) -> str | None:
        """Commit hash of the model snapshot in the local Hugging Face cache (for reproducibility)."""
        try:
            from huggingface_hub import try_to_load_from_cache
            path = try_to_load_from_cache(self.model_name, "config.json")
            parts = str(path).replace("\\", "/").split("/")
            return parts[parts.index("snapshots") + 1] if isinstance(path, str) and "snapshots" in parts else None
        except Exception:
            return None

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=False)
        if vectors.shape != (len(texts), self.dimensions):
            raise RuntimeError(f"unexpected embedding shape {vectors.shape}")
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" for t in texts]) if texts else []

    def embed_query(self, question: str) -> list[float]:
        return self._encode([f"query: {question}"])[0]

    def info(self) -> dict:
        return {"provider": "local sentence-transformers", "model": self.model_name, "revision": self.revision,
                "dimensions": self.dimensions, "max_seq_length": self.max_seq_length, "device": self.device,
                "normalize": True, "query_prefix": "query: ", "document_prefix": "passage: ", "cost_usd": 0.0}
