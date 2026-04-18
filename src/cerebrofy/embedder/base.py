"""Abstract base class for embedding providers."""

from __future__ import annotations

import abc


class Embedder(abc.ABC):
    """Embed a list of text strings. Returns one float vector per input text."""

    @property
    @abc.abstractmethod
    def dim(self) -> int:
        """Dimensionality of the embedding vectors produced by this model."""

    @abc.abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text strings. Returns one float vector per input text."""
