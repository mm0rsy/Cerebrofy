"""Embedding helper for memory bodies."""
from __future__ import annotations

from cerebrofy.embedder.local import LocalEmbedder


def embed_memory(title: str, body: str) -> list[float]:
  """Embed a memory's title + body into a 384-dim vector."""
  text = f"{title} {body}"
  embedder = LocalEmbedder()
  return embedder.embed([text])[0]
