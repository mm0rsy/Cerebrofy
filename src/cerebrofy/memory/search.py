"""KNN semantic search over memories using sqlite-vec."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from cerebrofy.memory.store import Memory, row_to_memory

_SELECT_COLS = (
    "m.id, m.neuron_id, m.lobe, m.type, m.title, m.body, m.author, "
    "m.created_ts, m.tags, m.decay_score, m.status"
)


def recall_memories(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int = 10,
    type_filter: str | None = None,
    lobe_filter: str | None = None,
    include_stale: bool = False,
) -> list[tuple[Memory, float]]:
    """KNN search on vec_memories. Returns (Memory, similarity_score) pairs desc."""
    where_clauses: list[str] = []
    extra_params: list[Any] = []

    if type_filter is not None:
        where_clauses.append("m.type = ?")
        extra_params.append(type_filter)
    if lobe_filter is not None:
        where_clauses.append("m.lobe = ?")
        extra_params.append(lobe_filter)
    if not include_stale:
        where_clauses.append("m.status != 'stale'")

    where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = (
        f"SELECT {_SELECT_COLS}, v.distance "
        f"FROM vec_memories v "
        f"JOIN memories m ON m.rowid = v.rowid "
        f"WHERE v.embedding MATCH vec_f32(?) AND k = ?{where_sql} "
        f"ORDER BY v.distance"
    )

    params: list[Any] = [json.dumps(query_embedding), limit] + extra_params
    rows = conn.execute(sql, params).fetchall()

    results: list[tuple[Memory, float]] = []
    for row in rows:
        mem = row_to_memory(row[:11])
        similarity = max(0.0, 1.0 - float(row[11]))
        results.append((mem, round(similarity, 4)))
    return results
