"""Scope resolver: depth-2 BFS to find affected nodes for incremental update."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cerebrofy.update.change_detector import ChangeSet


@dataclass(frozen=True)
class UpdateScope:
    changed_files: frozenset[str]
    deleted_files: frozenset[str]
    affected_node_ids: frozenset[str]
    affected_files: frozenset[str]


def _get_node_ids_for_files(
    conn: sqlite3.Connection, files: frozenset[str]
) -> set[str]:
    """Return all node IDs whose file is in the given file set."""
    if not files:
        return set()
    placeholders = ",".join("?" * len(files))
    rows = conn.execute(
        f"SELECT id FROM nodes WHERE file IN ({placeholders})", tuple(files)
    ).fetchall()
    return {row[0] for row in rows}


def _bfs_depth2(seed_ids: set[str], conn: sqlite3.Connection) -> set[str]:
    """BFS over edges (both directions) for exactly 2 hops; excludes RUNTIME_BOUNDARY.

    Returns all visited node IDs including seeds.
    """
    if not seed_ids:
        return set()

    visited = set(seed_ids)
    frontier = set(seed_ids)

    for _ in range(2):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        params = tuple(frontier)
        # Outbound edges (src → dst)
        rows_out = conn.execute(
            f"SELECT dst_id FROM edges "
            f"WHERE src_id IN ({placeholders}) AND rel_type != 'RUNTIME_BOUNDARY'",
            params,
        ).fetchall()
        # Inbound edges (dst → src)
        rows_in = conn.execute(
            f"SELECT src_id FROM edges "
            f"WHERE dst_id IN ({placeholders}) AND rel_type != 'RUNTIME_BOUNDARY'",
            params,
        ).fetchall()
        next_frontier: set[str] = set()
        for (nid,) in rows_out + rows_in:
            if nid not in visited:
                visited.add(nid)
                next_frontier.add(nid)
        frontier = next_frontier

    return visited


def _get_files_for_node_ids(
    conn: sqlite3.Connection, node_ids: set[str]
) -> set[str]:
    """Return distinct file paths for the given node IDs."""
    if not node_ids:
        return set()
    placeholders = ",".join("?" * len(node_ids))
    rows = conn.execute(
        f"SELECT DISTINCT file FROM nodes WHERE id IN ({placeholders})",
        tuple(node_ids),
    ).fetchall()
    return {row[0] for row in rows}


def resolve_scope(changeset: ChangeSet, conn: sqlite3.Connection) -> UpdateScope:
    """Build UpdateScope via depth-2 BFS from changed/deleted file nodes."""
    changed_files: frozenset[str] = frozenset(
        fc.path for fc in changeset.changes if fc.status in ("M", "A")
    )
    deleted_files: frozenset[str] = frozenset(
        fc.path for fc in changeset.changes if fc.status == "D"
    )
    seed_files = changed_files | deleted_files
    seed_ids = _get_node_ids_for_files(conn, seed_files)
    all_affected_ids = _bfs_depth2(seed_ids, conn)
    affected_files = frozenset(_get_files_for_node_ids(conn, all_affected_ids))
    return UpdateScope(
        changed_files=changed_files,
        deleted_files=deleted_files,
        affected_node_ids=frozenset(all_affected_ids),
        affected_files=affected_files,
    )
