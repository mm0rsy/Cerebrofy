"""Embedder factory — returns the configured embedding backend."""

from __future__ import annotations

from cerebrofy.embedder.base import Embedder


def get_embedder(embedding_model: str) -> Embedder:
    """Return the Embedder instance for the configured embedding_model name."""
    if embedding_model == "local":
        from cerebrofy.embedder.local import LocalEmbedder
        return LocalEmbedder()
    if embedding_model == "openai":
        from cerebrofy.embedder.openai_emb import OpenAIEmbedder
        return OpenAIEmbedder()
    if embedding_model == "cohere":
        from cerebrofy.embedder.cohere_emb import CohereEmbedder
        return CohereEmbedder()
    raise ValueError(f"Unknown embedding model: {embedding_model}")
