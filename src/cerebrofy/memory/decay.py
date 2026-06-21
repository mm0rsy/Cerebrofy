"""Memory decay scoring for the agent memory layer."""
from __future__ import annotations

import math
import sqlite3
import time as _time

from cerebrofy.config.loader import MemoryConfig
from cerebrofy.memory.store import Memory, row_to_memory

_SELECT_COLS = (
    "id, neuron_id, lobe, type, title, body, author, "
    "created_ts, tags, decay_score, status"
)


def compute_decay(
    memory: Memory,
    neuron_signature_changed: bool,
    current_ts: int,
    config: MemoryConfig,
) -> float:
    """Compute decay score (0.0–1.0).

    Time-based: exponential with configured half-life.
    Signature penalty: multiply by 0.3 if attached neuron changed.
    """
    days_since = max(0.0, (current_ts - memory.created_ts) / 86400.0)
    time_factor = math.exp(-math.log(2) / config.decay_half_life_days * days_since)
    stability_factor = 0.3 if neuron_signature_changed else 1.0
    score = round(time_factor * stability_factor, 4)
    return max(0.0, min(1.0, score))


def _decay_status(score: float, config: MemoryConfig) -> str:
    """Return status label for a given decay score."""
    if score < config.stale_threshold:
        return "stale"
    if score < config.possibly_stale_threshold:
        return "possibly_stale"
    return "active"


def recompute_all_decay(
    conn: sqlite3.Connection,
    changed_neuron_ids: set[str],
    config: MemoryConfig,
) -> int:
    """Recompute decay for all memories. Returns count of rows whose status changed.

    Pass empty set for build (time-decay only).
    Pass affected_node_ids for update (signature penalty for those neurons).
    """
    current_ts = int(_time.time())
    rows = conn.execute(
        f"SELECT {_SELECT_COLS} FROM memories"
    ).fetchall()

    changed_count = 0
    for row in rows:
        memory = row_to_memory(row)
        neuron_changed = (
            memory.neuron_id is not None and memory.neuron_id in changed_neuron_ids
        )
        new_score = compute_decay(memory, neuron_changed, current_ts, config)
        new_status = _decay_status(new_score, config)
        if new_score != memory.decay_score or new_status != memory.status:
            conn.execute(
                "UPDATE memories SET decay_score = ?, status = ? WHERE id = ?",
                (new_score, new_status, memory.id),
            )
            changed_count += 1
    return changed_count
