"""MCP Resource handlers for cerebrofy — URI-addressable ambient context.

Resources expose codebase graph data for AI clients as ambient context
(no explicit tool call required). Six resource types are supported:

  cerebrofy://graph/map                 → cerebrofy_map.md (full codebase map)
  cerebrofy://graph/entry-points        → entry-point neurons JSON
  cerebrofy://health/current            → latest health snapshot JSON
  cerebrofy://lobes/{name}              → {name}_lobe.md summary Markdown
  cerebrofy://neurons/{neuron_id}       → single neuron details JSON
  cerebrofy://memories/{neuron_id}      → memories attached to a neuron JSON
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _docs_dir(root: Path) -> Path:
    return root / "docs" / "cerebrofy"


def read_map(root: Path) -> str:
    """Return cerebrofy_map.md content, raising FileNotFoundError if missing."""
    path = _docs_dir(root) / "cerebrofy_map.md"
    if not path.exists():
        raise FileNotFoundError(
            "cerebrofy_map.md not found. Run 'cerebrofy build' first."
        )
    return path.read_text(encoding="utf-8")


def read_lobe(name: str, root: Path) -> str:
    """Return {name}_lobe.md content, raising FileNotFoundError if not indexed."""
    path = _docs_dir(root) / f"{name}_lobe.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Lobe '{name}' not found. Run 'cerebrofy build' first."
        )
    return path.read_text(encoding="utf-8")


def list_lobe_names(root: Path) -> list[str]:
    """Return sorted lobe names derived from *_lobe.md files on disk."""
    docs = _docs_dir(root)
    if not docs.exists():
        return []
    return sorted(
        p.stem[: -len("_lobe")]
        for p in docs.glob("*_lobe.md")
        if p.stem.endswith("_lobe")
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def entry_points(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return neurons with no incoming non-RUNTIME_BOUNDARY edges but with outgoing edges."""
    rows = conn.execute("""
        SELECT n.id, n.name, n.file, n.line_start, n.type
        FROM nodes n
        WHERE n.type != 'module'
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE e.dst_id = n.id AND e.rel_type != 'RUNTIME_BOUNDARY'
          )
          AND EXISTS (SELECT 1 FROM edges e WHERE e.src_id = n.id)
        ORDER BY n.file, n.line_start
    """).fetchall()
    return [
        {"id": r[0], "name": r[1], "file": r[2], "line_start": r[3], "type": r[4]}
        for r in rows
    ]


def get_neuron(neuron_id: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Fetch a single neuron by ID, returning None if not found."""
    row = conn.execute(
        "SELECT id, name, file, type, line_start, line_end, signature, docstring, hash "
        "FROM nodes WHERE id = ? LIMIT 1",
        (neuron_id,),
    ).fetchone()
    if not row:
        return None
    cols = ("id", "name", "file", "type", "line_start", "line_end",
            "signature", "docstring", "hash")
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Memory helper
# ---------------------------------------------------------------------------

def memories_for_neuron(neuron_id: str, root: Path) -> list[dict[str, Any]]:
    """Return memories attached to neuron_id. Returns [] if memories.db absent."""
    memories_db = root / ".cerebrofy" / "db" / "memories.db"
    if not memories_db.exists():
        return []
    try:
        from cerebrofy.memory.store import list_memories, open_memories_db
        conn = open_memories_db(root / ".cerebrofy")
        try:
            return [dataclasses.asdict(m) for m in list_memories(conn, neuron_id=neuron_id)]
        finally:
            conn.close()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Health helper
# ---------------------------------------------------------------------------

def current_health(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return the latest health snapshot dict, or None if none recorded yet."""
    from cerebrofy.health.snapshot import fetch_latest_snapshot
    return fetch_latest_snapshot(conn)
