"""Unit tests for memory/embedder.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


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
