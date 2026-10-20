"""Embedder factory — returns the configured embedding backend."""

from __future__ import annotations

from cerebrofy.embedder.base import Embedder

# Canonical, ordered allowlist of every identifier accepted by the
# ``embedding_model`` config field. Kept here — the single source of truth for
# embedder selection — so that both ``get_embedder`` (used directly by the
# build/update commands) and ``config/loader.py`` (used at config load time)
# validate against the exact same set. An unsupported value is rejected as
# early as possible (fail-fast) rather than passing silently through the
# factory.
SUPPORTED_EMBEDDING_MODELS: tuple[str, ...] = ("local", "none")


def validate_embedding_model(embedding_model: str) -> str:
    """Validate *embedding_model* against ``SUPPORTED_EMBEDDING_MODELS``.

    Returns the model name unchanged when it is recognised. Raises
    ``ValueError`` with a message listing the allowed values when the name is
    not one of the supported identifiers, so callers receive a clear,
    actionable error instead of an opaque failure at use time.
    """
    if embedding_model not in SUPPORTED_EMBEDDING_MODELS:
        allowed = ", ".join(repr(m) for m in SUPPORTED_EMBEDDING_MODELS)
        raise ValueError(
            f"Unsupported embedding_model {embedding_model!r}. "
            f"Allowed values: {allowed}."
        )
    return embedding_model


def get_embedder(embedding_model: str) -> Embedder | None:
    """Return the Embedder instance for the configured embedding_model name.

    Returns ``None`` when ``embedding_model`` is ``"none"`` — the caller is
    responsible for skipping the vector-embedding step in that case.

    Raises ``ValueError`` if *embedding_model* is not one of the supported
    identifiers (see ``SUPPORTED_EMBEDDING_MODELS``). Validation happens
    before any lazy import or backend construction, so unknown names fail fast.
    """
    validate_embedding_model(embedding_model)

    if embedding_model == "none":
        return None
    # embedding_model == "local" (guaranteed by validate_embedding_model above)
    from cerebrofy.embedder.local import LocalEmbedder
    return LocalEmbedder()
