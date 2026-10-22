"""Cerebrofy Multi-Agent Coordination — Memory Conflict Resolver.

Implements the four resolution strategies from the IDEA:

``keep_newest``
    Keep the memory with the highest ``created_ts`` (ties broken by the
    lexicographically higher id), mark the other ``stale``.

``keep_by_author``
    Keep the memory authored by the requested author, mark the other stale.

``human_review``
    Mutate nothing; flag the pair for a human to decide.

``merge``
    Write a new memory with a human-supplied body, mark both originals stale.

All mutations are committed atomically against ``.cerebrofy/db/memories.db``.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from cerebrofy.coordination.constants import RESOLUTION_OPTIONS
from cerebrofy.db.connection import open_db, write_transaction
from cerebrofy.db.schema import create_memory_schema
from cerebrofy.memory import embedder
from cerebrofy.memory.store import Memory, get_memory, write_memory


class ResolutionStrategy(Enum):
    """Available memory conflict resolution strategies."""

    KEEP_MOST_RECENT = "keep_newest"
    KEEP_BY_AUTHOR = "keep_by_author"
    HUMAN_REVIEW = "human_review"
    MERGE = "merge"


_STRATEGY_ALIASES: dict[str, ResolutionStrategy] = {
    "newest": ResolutionStrategy.KEEP_MOST_RECENT,
    "keep_newest": ResolutionStrategy.KEEP_MOST_RECENT,
    "keep_most_recent": ResolutionStrategy.KEEP_MOST_RECENT,
    "author": ResolutionStrategy.KEEP_BY_AUTHOR,
    "keep_by_author": ResolutionStrategy.KEEP_BY_AUTHOR,
    "human_review": ResolutionStrategy.HUMAN_REVIEW,
    "human-review": ResolutionStrategy.HUMAN_REVIEW,
    "review": ResolutionStrategy.HUMAN_REVIEW,
    "merge": ResolutionStrategy.MERGE,
}


class ConflictResolver:
    """Resolves a pair of contradicting memories using a chosen strategy."""

    def __init__(
        self,
        cerebrofy_dir: str | Path,
        *,
        memories_db_path: str | Path | None = None,
    ) -> None:
        self.cerebrofy_dir = Path(cerebrofy_dir)
        self.memories_db_path = (
            Path(memories_db_path)
            if memories_db_path is not None
            else self.cerebrofy_dir / "db" / "memories.db"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_pair(
        self,
        memory_a_id: str,
        memory_b_id: str,
        strategy: ResolutionStrategy | str,
        *,
        neuron: str | None = None,
        author: str | None = None,
        merged_body: str | None = None,
    ) -> dict[str, Any]:
        """Resolve the conflict between two memories.

        Raises ``ValueError`` when both ids are the same, for unknown memory
        ids, a missing ``author`` with ``keep_by_author``, a missing
        ``merged_body`` with ``merge``, or an author that authored neither
        memory.
        """
        if memory_a_id == memory_b_id:
            raise ValueError(
                f"Cannot resolve memory {memory_a_id!r} against itself."
            )
        resolved_strategy = _normalize_strategy(strategy)
        conn = self._open()
        try:
            memory_a = get_memory(conn, memory_a_id)
            memory_b = get_memory(conn, memory_b_id)
            if memory_a is None:
                raise ValueError(f"Memory {memory_a_id!r} not found.")
            if memory_b is None:
                raise ValueError(f"Memory {memory_b_id!r} not found.")

            if resolved_strategy is ResolutionStrategy.HUMAN_REVIEW:
                # No mutation — a human decides.
                return {
                    "resolved": False,
                    "requires_review": True,
                    "strategy": resolved_strategy.value,
                    "memory_a": _memory_payload(memory_a),
                    "memory_b": _memory_payload(memory_b),
                    "resolution_options": list(RESOLUTION_OPTIONS),
                }

            if resolved_strategy is ResolutionStrategy.MERGE:
                return self._resolve_merge(
                    conn,
                    memory_a,
                    memory_b,
                    neuron=neuron,
                    author=author,
                    merged_body=merged_body,
                )

            if resolved_strategy is ResolutionStrategy.KEEP_BY_AUTHOR:
                winner, loser = self._pick_by_author(memory_a, memory_b, author)
            else:
                winner, loser = self._pick_newest(memory_a, memory_b)

            with write_transaction(conn):
                conn.execute(
                    "UPDATE memories SET status = 'stale' WHERE id = ?",
                    (loser.id,),
                )

            return {
                "resolved": True,
                "requires_review": False,
                "strategy": resolved_strategy.value,
                "winner": winner.id,
                "loser": loser.id,
                "memory_a": _memory_payload(memory_a),
                "memory_b": _memory_payload(memory_b),
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_newest(
        memory_a: Memory, memory_b: Memory
    ) -> tuple[Memory, Memory]:
        """Pick the newest memory; ties go to the higher id lexicographically."""
        if (memory_a.created_ts, memory_a.id) >= (memory_b.created_ts, memory_b.id):
            return memory_a, memory_b
        return memory_b, memory_a

    @staticmethod
    def _pick_by_author(
        memory_a: Memory, memory_b: Memory, author: str | None
    ) -> tuple[Memory, Memory]:
        if not author:
            raise ValueError("--author is required for keep_by_author.")
        matches = [memory for memory in (memory_a, memory_b) if memory.author == author]
        if not matches:
            raise ValueError(
                f"Neither memory was authored by {author!r}; cannot apply "
                "keep_by_author."
            )
        if len(matches) == 1:
            winner = matches[0]
            loser = memory_b if winner is memory_a else memory_a
            return winner, loser
        return ConflictResolver._pick_newest(memory_a, memory_b)

    def _resolve_merge(
        self,
        conn: sqlite3.Connection,
        memory_a: Memory,
        memory_b: Memory,
        *,
        neuron: str | None,
        author: str | None,
        merged_body: str | None,
    ) -> dict[str, Any]:
        if not merged_body:
            raise ValueError(
                "A merged memory body is required for the merge strategy."
            )

        title = f"Merged: {memory_a.title}"
        merged = Memory(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            neuron_id=neuron or memory_a.neuron_id,
            lobe=memory_a.lobe,
            type=memory_a.type,
            title=title,
            body=merged_body,
            author=author,
            created_ts=int(time.time()),
            tags=("merged",),
            decay_score=1.0,
            status="active",
        )
        embedding = embedder.embed_memory(title, merged_body)

        with write_transaction(conn):
            write_memory(conn, merged, embedding)
            conn.execute(
                "UPDATE memories SET status = 'stale' WHERE id IN (?, ?)",
                (memory_a.id, memory_b.id),
            )

        return {
            "resolved": True,
            "requires_review": False,
            "strategy": ResolutionStrategy.MERGE.value,
            "winner": merged.id,
            "superseded": [memory_a.id, memory_b.id],
            "memory_a": _memory_payload(memory_a),
            "memory_b": _memory_payload(memory_b),
            "merged_memory": _memory_payload(merged),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        self.memories_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = open_db(self.memories_db_path)
        create_memory_schema(conn)
        return conn


def _normalize_strategy(strategy: ResolutionStrategy | str) -> ResolutionStrategy:
    if isinstance(strategy, ResolutionStrategy):
        return strategy
    normalized = _STRATEGY_ALIASES.get(str(strategy).strip().lower())
    if normalized is None:
        raise ValueError(f"Unknown resolution strategy: {strategy!r}")
    return normalized


def _memory_payload(memory: Memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "neuron_id": memory.neuron_id,
        "lobe": memory.lobe,
        "type": memory.type,
        "title": memory.title,
        "body": memory.body,
        "author": memory.author,
        "created_ts": memory.created_ts,
        "tags": list(memory.tags),
        "decay_score": memory.decay_score,
        "status": memory.status,
    }


__all__ = ["ConflictResolver", "ResolutionStrategy", "RESOLUTION_OPTIONS"]
