"""OpenAI embedding provider (text-embedding-3-small, 1536-dim)."""

from __future__ import annotations

from cerebrofy.embedder.base import Embedder


class OpenAIEmbedder(Embedder):
    """Embed texts via OpenAI text-embedding-3-small API (1536-dim)."""

    def __init__(self) -> None:
        import openai  # type: ignore[import-untyped]
        self.client = openai.OpenAI()  # reads OPENAI_API_KEY from env

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in chunks of 512. Returns one 1536-dim vector per text."""
        results: list[list[float]] = []
        for i in range(0, len(texts), 512):
            chunk = texts[i:i + 512]
            response = self.client.embeddings.create(
                model="text-embedding-3-small",
                input=chunk,
            )
            results.extend(item.embedding for item in response.data)
        return results
