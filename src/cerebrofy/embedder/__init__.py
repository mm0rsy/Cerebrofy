"""Embedder factory — returns the configured embedding backend."""

from __future__ import annotations

from cerebrofy.embedder.base import Embedder


def get_embedder(embedding_model: str) -> Embedder | None:
    """Return the Embedder instance for the configured embedding_model name.

    Returns ``None`` when ``embedding_model`` is ``"none"`` — the caller is
    responsible for skipping the vector-embedding step in that case.
    """
    if embedding_model == "none":
        return None
    if embedding_model == "local":
        from cerebrofy.embedder.local import LocalEmbedder
        return LocalEmbedder()
    raise ValueError(
        f"Unknown embedding model: {embedding_model!r}. "
        "Supported values: 'local', 'none'."
    )
