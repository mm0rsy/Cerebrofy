"""Unit tests for cerebrofy.memory.embedder and the embedder factory."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cerebrofy.embedder import (
    SUPPORTED_EMBEDDING_MODELS,
    get_embedder,
    validate_embedding_model,
)


def test_embed_memory_concatenates_title_and_body():
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.5] * 384]
    with patch("cerebrofy.memory.embedder.LocalEmbedder", return_value=mock_embedder):
        from cerebrofy.memory.embedder import embed_memory
        result = embed_memory("Clock skew", "Token expiry breaks with drift > 30s")
    mock_embedder.embed.assert_called_once()
    call_text = mock_embedder.embed.call_args[0][0][0]
    assert "Clock skew" in call_text
    assert "Token expiry" in call_text
    assert result == [0.5] * 384


def test_embed_memory_returns_384_floats():
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 384]
    with patch("cerebrofy.memory.embedder.LocalEmbedder", return_value=mock_embedder):
        from cerebrofy.memory.embedder import embed_memory
        result = embed_memory("title", "body")
    assert len(result) == 384
    assert all(isinstance(x, float) for x in result)


# ---------------------------------------------------------------------------
# Embedder factory (cerebrofy.embedder) allowlist hardening
# ---------------------------------------------------------------------------


def test_supported_embedding_models_allowlist() -> None:
    assert SUPPORTED_EMBEDDING_MODELS == ("local", "none")


def test_get_embedder_none_returns_none() -> None:
    """'none' behaviour unchanged: get_embedder('none') returns None."""
    assert get_embedder("none") is None


def test_get_embedder_local_returns_instance() -> None:
    """'local' returns a LocalEmbedder instance (fastembed mocked)."""
    mock_embedder = MagicMock()
    with patch("cerebrofy.embedder.local.LocalEmbedder", return_value=mock_embedder):
        result = get_embedder("local")
    assert result is mock_embedder


@pytest.mark.parametrize(
    "model", ["weird", "openai", "cohere", "", "LOCAL", " local "]
)
def test_get_embedder_rejects_unknown(model: str) -> None:
    with pytest.raises(ValueError, match="Unsupported embedding_model"):
        get_embedder(model)


def test_get_embedder_error_lists_allowed_values() -> None:
    with pytest.raises(ValueError) as exc_info:
        get_embedder("weird")
    msg = str(exc_info.value)
    assert "Unsupported embedding_model 'weird'" in msg
    assert "'local'" in msg
    assert "'none'" in msg


def test_validate_embedding_model_returns_input() -> None:
    for model in SUPPORTED_EMBEDDING_MODELS:
        assert validate_embedding_model(model) == model
