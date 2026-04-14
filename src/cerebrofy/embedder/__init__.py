"""Embedder factory — returns the configured embedding backend."""

from __future__ import annotations

from cerebrofy.embedder.base import Embedder


class MissingOptionalDependencyError(ValueError):
    """Raised when an embedding backend dependency is not installed."""


def _install_hint(extra_name: str) -> str:
    command = f"cerebrofy[{extra_name}]"
    return (
        f"Install it with `pip install '{command}'`, "
        f"`pipx install '{command}'`, or `uv tool install '{command}'`."
    )


def get_embedder(embedding_model: str) -> Embedder:
    """Return the Embedder instance for the configured embedding_model name."""
    if embedding_model == "local":
        try:
            from cerebrofy.embedder.local import LocalEmbedder
            return LocalEmbedder()
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependencyError(
                "Local embeddings require the optional 'local' extra. "
                + _install_hint("local")
            ) from exc
    if embedding_model == "openai":
        try:
            from cerebrofy.embedder.openai_emb import OpenAIEmbedder
            return OpenAIEmbedder()
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependencyError(
                "OpenAI embeddings require the optional 'openai' extra. "
                + _install_hint("openai")
            ) from exc
    if embedding_model == "cohere":
        try:
            from cerebrofy.embedder.cohere_emb import CohereEmbedder
            return CohereEmbedder()
        except ModuleNotFoundError as exc:
            raise MissingOptionalDependencyError(
                "Cohere embeddings require the optional 'cohere' extra. "
                + _install_hint("cohere")
            ) from exc
    raise ValueError(f"Unknown embedding model: {embedding_model}")
