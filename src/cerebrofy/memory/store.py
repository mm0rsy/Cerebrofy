"""Writable memory store for Cerebrofy. Uses a separate memories.db file."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VALID_TYPES = frozenset({"decision", "warning", "context", "pattern", "agent_action", "insight"})
VALID_REL_TYPES = frozenset({"caused", "motivated", "resolved", "contradicts", "updated_by"})


@dataclass(frozen=True)
class Memory:
    id: str
    neuron_id: str | None
    lobe: str | None
    type: str
    title: str
    body: str
    author: str | None
    created_ts: int
    tags: tuple[str, ...]
    decay_score: float
    status: str  # active | possibly_stale | stale


@dataclass(frozen=True)
class MemoryEdge:
    from_memory_id: str
    to_memory_id: str
    rel_type: str
    created_ts: int
    author: str | None


def open_memories_db(cerebrofy_dir: Path) -> sqlite3.Connection:
    """Open (or create) memories.db, load sqlite-vec, create schema idempotently."""
    import sqlite_vec  # type: ignore[import-untyped]
    db_path = cerebrofy_dir / "db" / "memories.db"
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    from cerebrofy.db.schema import create_memory_schema
    create_memory_schema(conn)
    return conn


def row_to_memory(row: tuple[Any, ...]) -> Memory:
    """Convert a DB row (11 columns) to a Memory dataclass."""
    id_, neuron_id, lobe, type_, title, body, author, created_ts, tags_str, decay_score, status = row
    tags: tuple[str, ...] = tuple(
        t.strip() for t in tags_str.split(",") if t.strip()
    ) if tags_str else ()
    return Memory(
        id=id_, neuron_id=neuron_id, lobe=lobe, type=type_,
        title=title, body=body, author=author, created_ts=int(created_ts),
        tags=tags, decay_score=float(decay_score), status=status,
    )
