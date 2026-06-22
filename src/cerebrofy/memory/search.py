"""KNN semantic search over memories using sqlite-vec."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from cerebrofy.memory.store import Memory, _SELECT_COLS, row_to_memory


def recall_memories(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int = 10,
    type_filter: str | None = None,
    lobe_filter: str | None = None,
    include_stale: bool = False,
) -> list[tuple[Memory, float]]:
    """KNN search on vec_memories. Returns (Memory, similarity_score) pairs desc.

    Uses a two-step approach: oversample from vec_memories first, then apply
    filters on the memories table. This avoids the sqlite-vec problem where
    post-k WHERE clauses are applied after the scan cap, silently returning
    fewer results than requested.
    """
    # Step 1: Oversample from vec — fetch more than needed to allow for filtering
    oversample_k = max(limit * 20, 100)
    vec_rows = conn.execute(
        "SELECT rowid, distance FROM vec_memories "
        "WHERE embedding MATCH vec_f32(?) AND k = ?",
        (json.dumps(query_embedding), oversample_k),
    ).fetchall()

    if not vec_rows:
        return []

    rowid_to_dist: dict[int, float] = {int(r[0]): float(r[1]) for r in vec_rows}
    rowids = list(rowid_to_dist.keys())

    # Step 2: Filter from memories table with requested criteria
    placeholders = ",".join("?" * len(rowids))
    where_parts = [f"rowid IN ({placeholders})"]
    filter_params: list[Any] = rowids[:]

    if type_filter is not None:
        where_parts.append("type = ?")
        filter_params.append(type_filter)
    if lobe_filter is not None:
        where_parts.append("lobe = ?")
        filter_params.append(lobe_filter)
    if not include_stale:
        where_parts.append("status != 'stale'")

    where_sql = " AND ".join(where_parts)
    mem_rows = conn.execute(
        f"SELECT rowid, {_SELECT_COLS} FROM memories WHERE {where_sql}",
        filter_params,
    ).fetchall()

    # Step 3: Join with distances, sort by similarity, truncate to limit
    results: list[tuple[Memory, float]] = []
    for row in mem_rows:
        rowid = int(row[0])
        mem = row_to_memory(row[1:])  # 11 columns after rowid
        similarity = max(0.0, 1.0 - rowid_to_dist[rowid])
        results.append((mem, round(similarity, 4)))

    results.sort(key=lambda x: -x[1])
    return results[:limit]
