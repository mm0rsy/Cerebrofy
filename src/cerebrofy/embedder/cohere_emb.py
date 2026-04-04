"""Cohere embedding provider (embed-english-v3.0, 1024-dim)."""

from __future__ import annotations

import os

from cerebrofy.embedder.base import Embedder


class CohereEmbedder(Embedder):
    """Embed texts via Cohere embed-english-v3.0 API (1024-dim)."""

    def __init__(self) -> None:
        import cohere  # type: ignore[import-untyped]
        self.co = cohere.Client(os.environ["COHERE_API_KEY"])

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in chunks of 96. Returns one 1024-dim vector per text."""
        results: list[list[float]] = []
        for i in range(0, len(texts), 96):
            chunk = texts[i:i + 96]
            response = self.co.embed(
                texts=chunk,
                model="embed-english-v3.0",
                input_type="search_document",
            )
            results.extend(response.embeddings)
        return results
