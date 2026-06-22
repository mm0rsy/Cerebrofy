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


_SELECT_COLS = (
    "id, neuron_id, lobe, type, title, body, author, "
    "created_ts, tags, decay_score, status"
)


def write_memory(
    conn: sqlite3.Connection, memory: Memory, embedding: list[float]
) -> None:
    """Insert memory into memories + vec_memories. Caller must commit."""
    import json
    tags_str = ",".join(memory.tags) if memory.tags else ""
    cursor = conn.execute(
        f"INSERT INTO memories({_SELECT_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (memory.id, memory.neuron_id, memory.lobe, memory.type, memory.title,
         memory.body, memory.author, memory.created_ts, tags_str,
         memory.decay_score, memory.status),
    )
    rowid = cursor.lastrowid
    conn.execute(
        "INSERT INTO vec_memories(rowid, embedding) VALUES (?, vec_f32(?))",
        (rowid, json.dumps(embedding)),
    )


def get_memory(conn: sqlite3.Connection, memory_id: str) -> Memory | None:
    """Return a single Memory by id, or None if not found."""
    row = conn.execute(
        f"SELECT {_SELECT_COLS} FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    return row_to_memory(row) if row else None


def list_memories(
    conn: sqlite3.Connection,
    neuron_id: str | None = None,
    lobe: str | None = None,
    type_filter: str | None = None,
    include_stale: bool = False,
) -> list[Memory]:
    """Return memories matching optional filters, ordered by created_ts DESC."""
    q = f"SELECT {_SELECT_COLS} FROM memories WHERE 1=1"
    params: list[Any] = []
    if neuron_id is not None:
        q += " AND neuron_id = ?"
        params.append(neuron_id)
    if lobe is not None:
        q += " AND lobe = ?"
        params.append(lobe)
    if type_filter is not None:
        q += " AND type = ?"
        params.append(type_filter)
    if not include_stale:
        q += " AND status != 'stale'"
    q += " ORDER BY created_ts DESC"
    return [row_to_memory(r) for r in conn.execute(q, params).fetchall()]


def delete_memory(conn: sqlite3.Connection, memory_id: str) -> None:
    """Delete memory and its vec_memories entry. Caller must commit."""
    row = conn.execute("SELECT rowid FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row:
        conn.execute("DELETE FROM vec_memories WHERE rowid = ?", (row[0],))
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))


def write_memory_edge(conn: sqlite3.Connection, edge: MemoryEdge) -> None:
    """Insert a causal edge between two memories. Caller must commit."""
    conn.execute(
        "INSERT OR REPLACE INTO memory_edges"
        "(from_memory_id, to_memory_id, rel_type, created_ts, author) VALUES (?,?,?,?,?)",
        (edge.from_memory_id, edge.to_memory_id, edge.rel_type,
         edge.created_ts, edge.author),
    )


def trace_history(
    conn: sqlite3.Connection, memory_id: str, depth: int = 5
) -> list[Memory]:
    """Walk memory_edges backward from memory_id up to depth hops."""
    visited: set[str] = set()
    result: list[Memory] = []
    frontier = [memory_id]
    for _ in range(depth):
        if not frontier:
            break
        next_frontier: list[str] = []
        for mid in frontier:
            if mid in visited:
                continue
            visited.add(mid)
            m = get_memory(conn, mid)
            if m:
                result.append(m)
            rows = conn.execute(
                "SELECT from_memory_id FROM memory_edges WHERE to_memory_id = ?",
                (mid,),
            ).fetchall()
            next_frontier.extend(r[0] for r in rows if r[0] not in visited)
        frontier = next_frontier
    return result
