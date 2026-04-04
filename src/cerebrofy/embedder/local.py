"""Local embedding provider using sentence-transformers (offline, no API key)."""

from __future__ import annotations

from cerebrofy.embedder.base import Embedder


class LocalEmbedder(Embedder):
    """Embed texts using nomic-embed-text-v1 via sentence-transformers (768-dim, offline)."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer("nomic-ai/nomic-embed-text-v1")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches of 64. Returns one 768-dim vector per text."""
        result = self.model.encode(texts, batch_size=64, show_progress_bar=False)
        return [vec.tolist() for vec in result]
