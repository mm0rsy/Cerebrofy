"""Local embedding provider using fastembed (offline, no API key, no PyTorch)."""

from __future__ import annotations

import warnings

from cerebrofy.embedder.base import Embedder


class LocalEmbedder(Embedder):
    """Embed texts using BAAI/bge-small-en-v1.5 via fastembed (384-dim, ~130MB, ONNX)."""

    def __init__(self) -> None:
        # BAAI/bge-small-en-v1.5 is a public model — no HF token needed.
        # Suppress huggingface_hub's token-not-set warnings that appear on first download.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")
            warnings.filterwarnings("ignore", message=".*token.*", category=FutureWarning)
            from fastembed import TextEmbedding
            self.model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    @property
    def dim(self) -> int:
        return 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches. Returns one 384-dim vector per text."""
        return [vec.tolist() for vec in self.model.embed(texts)]
