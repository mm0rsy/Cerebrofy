"""Cerebrofy Multi-Agent Coordination — core package (Idea #25).

Public surface:

* :class:`~cerebrofy.coordination.registry.ActiveAgentRegistry` — persistent
  claim registry backed by ``.cerebrofy/db/cerebrofy.db``.
* :class:`~cerebrofy.coordination.conflict_detector.ConflictDetector` — claim
  collisions, overlapping claims, lobe awareness and memory contradictions.
* :class:`~cerebrofy.coordination.resolver.ConflictResolver` — keep_newest,
  keep_by_author, human_review and merge strategies for memory conflicts.

Coordination state (claims) is ephemeral: rebuilding the index recreates
``cerebrofy.db``.  Memory conflicts are resolved in ``memories.db`` and persist.
"""

from cerebrofy.coordination.conflict_detector import (
    CONTRADICTION_PATTERNS,
    RESOLUTION_OPTIONS,
    ConflictDetector,
)
from cerebrofy.coordination.registry import ActiveAgentRegistry
from cerebrofy.coordination.resolver import ConflictResolver, ResolutionStrategy

__all__ = [
    "CONTRADICTION_PATTERNS",
    "RESOLUTION_OPTIONS",
    "ActiveAgentRegistry",
    "ConflictDetector",
    "ConflictResolver",
    "ResolutionStrategy",
]

__version__ = "1.0.0"
