"""Combined semantic + graph relevance scoring for context candidates."""

from __future__ import annotations


def compute_relevance(
    semantic_score: float,
    is_seed: bool,
) -> float:
    """Return a combined relevance score for a candidate neuron.

    score = semantic_score * 0.6 + graph_proximity * 0.4

    graph_proximity is 1.0 for KNN seeds, 0.5 for BFS neighbors (depth-1).
    """
    graph_proximity = 1.0 if is_seed else 0.5
    return semantic_score * 0.6 + graph_proximity * 0.4
