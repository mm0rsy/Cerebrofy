"""Cerebrofy Multi-Agent Coordination — Conflict Detector.

Two kinds of conflicts matter when several agents share a codebase:

1. **Claim conflicts** — another active agent already claimed a neuron.
2. **Memory contradictions** — two memories on the same neuron say opposite
   things ("never use X" vs "X is fine").

Claim detection delegates to :class:`~cerebrofy.coordination.registry.ActiveAgentRegistry`.
Memory contradictions use the Phase-1 keyword-opposition heuristic from the
IDEA (``never X`` vs ``X is fine``, ``always Y`` vs ``Y is not required``,
``deprecated`` vs ``recommended``).  The heuristic is deliberately
conservative: when a pattern captures a subject (e.g. ``datetime.now``) the two
memories must talk about the same subject before a contradiction is reported.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cerebrofy.coordination.constants import RESOLUTION_OPTIONS

if TYPE_CHECKING:  # pragma: no cover - import cycle only for type checking
    from cerebrofy.coordination.registry import ActiveAgentRegistry

#: Keyword-opposition pattern pairs (Phase 1 heuristic).
#:
#: Each entry is ``(pattern_a, pattern_b)``.  When a pattern has a capture
#: group, the captured subject must match (or overlap) between the two bodies.
#: Entries without capture groups (e.g. the bare ``deprecated`` /
#: ``recommended`` pair) match on keyword presence alone.
CONTRADICTION_PATTERNS: list[tuple[str, str]] = [
    # "never X" vs "X is fine"
    (
        r"\bnever\s+(?:use\s+|call\s+)?([a-z_][\w.]*)",
        r"\b([a-z_][\w.]*(?:\s+[a-z_][\w.]*){0,3})(?:\(\))?\s+is\s+"
        r"(?:fine|ok(?:ay)?|acceptable|recommended|good|safe)\b",
    ),
    # "always Y" vs "Y is not required"
    (
        r"\balways\s+(?:use\s+)?([a-z_][\w.]*)",
        r"\b([a-z_][\w.]*(?:\s+[a-z_][\w.]*){0,3})(?:\(\))?\s+is\s+"
        r"(?:not\s+required|optional|unnecessary|deprecated)\b",
    ),
    # "deprecated" vs "recommended" (keyword-only: the IDEA's canonical pair)
    (r"\bdeprecated\b", r"\brecommended\b"),
    (r"\bdeprecated\b", r"\bpreferred\b"),
    # "avoid X" vs "use X"
    (
        r"\bavoid\s+([a-z_][\w.]*)",
        r"\buse\s+(?:the\s+)?([a-z_][\w.]*)",
    ),
    # "don't use X" vs "X is fine"
    (
        r"\b(?:don'?t|do\s+not)\s+use\s+([a-z_][\w.]*)",
        r"\b([a-z_][\w.]*(?:\s+[a-z_][\w.]*){0,3})(?:\(\))?\s+is\s+"
        r"(?:fine|ok(?:ay)?|acceptable|recommended)\b",
    ),
    # "remove/delete X" vs "add/keep X"
    (
        r"\b(?:remove|delete)\s+([a-z_][\w.]*)",
        r"\b(?:add|keep|retain)\s+([a-z_][\w.]*)",
    ),
    # "X is broken" vs "X works"
    (
        r"\b([a-z_][\w.]*)\s+is\s+(?:broken|bad|wrong|buggy)\b",
        r"\b([a-z_][\w.]*)\s+(?:works|is\s+correct|is\s+fixed)\b",
    ),
]


class ConflictDetector:
    """Detects claim collisions and memory contradictions for a codebase."""

    def __init__(
        self,
        registry: ActiveAgentRegistry | None = None,
        memories_db_path: str | Path | None = None,
    ) -> None:
        self.registry = registry
        self.memories_db_path = (
            Path(memories_db_path) if memories_db_path is not None else None
        )
        self.patterns = CONTRADICTION_PATTERNS

    # ------------------------------------------------------------------
    # Claim conflicts
    # ------------------------------------------------------------------

    def detect_claim_conflicts(
        self, neuron: str, requesting_agent: str
    ) -> dict[str, Any]:
        """Return other active agents claiming *neuron*.

        The requesting agent is always excluded.  ``claiming_agents`` is the
        canonical key; ``claim_conflicts`` is kept as an alias for the MCP
        middleware hook.
        """
        if self.registry is None:
            return {
                "neuron": neuron,
                "claiming_agents": [],
                "claim_conflicts": [],
                "has_conflict": False,
            }

        info = self.registry.check_conflicts(requesting_agent, neuron)
        agents = info["claiming_agents"]
        return {
            "neuron": neuron,
            "claiming_agents": agents,
            "claim_conflicts": agents,
            "has_conflict": bool(agents),
        }

    def detect_overlapping_claims(self) -> list[dict[str, Any]]:
        """Return neurons claimed by more than one active agent."""
        if self.registry is None:
            return []
        return self.registry.detect_overlapping_claims()

    def detect_lobe_awareness(
        self, neuron: str, requesting_agent: str
    ) -> list[dict[str, Any]]:
        """Return other agents working in the same lobe as *neuron*.

        Neuron ids look like ``auth/tokens.py::validate_token``; the lobe is the
        first path segment (``auth``).
        """
        if self.registry is None or "/" not in neuron:
            return []

        lobe = neuron.split("/", 1)[0]
        awareness: list[dict[str, Any]] = []
        for agent_id, data in self.registry.get_active_agents().items():
            if agent_id == requesting_agent:
                continue
            if any(
                claimed.split("/", 1)[0] == lobe
                for claimed in data["claimed_neurons"]
            ):
                awareness.append(
                    {
                        "agent_id": agent_id,
                        "agent_type": data["agent_type"],
                        "intent": data["intent"],
                        "active_minutes": data["active_minutes"],
                    }
                )
        return awareness

    # ------------------------------------------------------------------
    # Memory contradictions
    # ------------------------------------------------------------------

    def detect_memory_contradictions(
        self, neuron: str, memories: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Detect contradicting memory pairs on *neuron*, deduplicated by id."""
        contradictions: list[dict[str, Any]] = []
        seen: set[frozenset[str]] = set()

        for index, mem_a in enumerate(memories):
            for mem_b in memories[index + 1 :]:
                id_a = str(mem_a.get("id") or "")
                id_b = str(mem_b.get("id") or "")
                if not id_a or not id_b or id_a == id_b:
                    continue
                pair = frozenset((id_a, id_b))
                if pair in seen:
                    continue

                matched = self._check_contradiction(mem_a, mem_b)
                if matched is None:
                    continue

                seen.add(pair)
                contradictions.append(
                    {
                        "neuron": neuron,
                        "memory_a": _memory_ref(mem_a),
                        "memory_b": _memory_ref(mem_b),
                        "type": "keyword_opposition",
                        "matched_pattern": matched,
                        "resolution_options": list(RESOLUTION_OPTIONS),
                    }
                )

        return contradictions

    def detect_memory_conflicts(
        self, neuron: str | None = None
    ) -> list[dict[str, Any]]:
        """Load non-stale memories from ``memories.db`` and detect contradictions.

        This includes both ``active`` and ``possibly_stale`` memories, since a
        low decay score does not make a memory's advice any less contradictory.
        Only memories for *neuron* are considered when it is provided;
        otherwise every neuron with two or more non-stale memories is scanned.
        A missing database (or missing ``memories`` table) yields ``[]``.
        """
        db_path = self._resolve_memories_path()
        if db_path is None or not db_path.exists():
            return []

        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(db_path))
            query = (
                "SELECT id, neuron_id, body, author, created_ts FROM memories "
                "WHERE status != 'stale'"
            )
            params: tuple[Any, ...] = ()
            if neuron is not None:
                query += " AND neuron_id = ?"
                params = (neuron,)
            rows = conn.execute(query, params).fetchall()
        except sqlite3.Error:
            return []
        finally:
            if conn is not None:
                conn.close()

        by_neuron: dict[str, list[dict[str, Any]]] = {}
        for memory_id, neuron_id, body, author, created_ts in rows:
            if not neuron_id:
                continue
            by_neuron.setdefault(str(neuron_id), []).append(
                {
                    "id": str(memory_id),
                    "body": body or "",
                    "author": author,
                    "created_ts": int(created_ts),
                }
            )

        results: list[dict[str, Any]] = []
        for neuron_id, memories in sorted(by_neuron.items()):
            if len(memories) > 1:
                results.extend(
                    self.detect_memory_contradictions(neuron_id, memories)
                )
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_memories_path(self) -> Path | None:
        """Resolve the memories DB path from the explicit path or registry."""
        path = self.memories_db_path
        if path is not None:
            # Accept either a direct DB file or a ``.cerebrofy`` directory.
            # A not-yet-created ``.cerebrofy`` path must still be treated as a
            # directory, not as a bogus database file.
            if path.is_dir() or path.name == ".cerebrofy":
                return path / "db" / "memories.db"
            return path
        if self.registry is not None:
            return self.registry.db_path.parent / "memories.db"
        return None

    def _check_contradiction(
        self, mem_a: dict[str, Any], mem_b: dict[str, Any]
    ) -> str | None:
        """Return the matched pattern description, or ``None``."""
        body_a = str(mem_a.get("body") or "").lower()
        body_b = str(mem_b.get("body") or "").lower()
        if not body_a or not body_b:
            return None

        for pattern_a, pattern_b in self.patterns:
            for first, second in ((pattern_a, pattern_b), (pattern_b, pattern_a)):
                match_a = re.search(first, body_a)
                match_b = re.search(second, body_b)
                if match_a is None or match_b is None:
                    continue

                subject_a = _capture_subject(match_a)
                subject_b = _capture_subject(match_b)
                if (
                    subject_a
                    and subject_b
                    and not _subjects_overlap(subject_a, subject_b)
                ):
                    continue

                return f'"{first}" vs "{second}"'
        return None


def _memory_ref(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": memory.get("id"),
        "body": memory.get("body", ""),
        "author": memory.get("author"),
    }


def _capture_subject(match: re.Match[str]) -> str:
    """Return the first capture group, or ``""`` for keyword-only patterns."""
    if match.lastindex is None:
        return ""
    return str(match.group(1) or "").strip().lower()


def _subjects_overlap(subject_a: str, subject_b: str) -> bool:
    """Compare captured subjects, tolerating multi-word phrases.

    ``type`` and ``type hints`` are considered the same subject ("type hints"
    contains "type"), while ``datetime.now`` and ``date.today`` are not.
    """
    if subject_a == subject_b:
        return True
    tokens_a = set(re.findall(r"[a-z_][\w.]*", subject_a))
    tokens_b = set(re.findall(r"[a-z_][\w.]*", subject_b))
    return bool(tokens_a & tokens_b)


__all__ = [
    "CONTRADICTION_PATTERNS",
    "RESOLUTION_OPTIONS",
    "ConflictDetector",
]
