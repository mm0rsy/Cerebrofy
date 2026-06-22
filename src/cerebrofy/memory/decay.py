"""Memory decay scoring for the agent memory layer."""
from __future__ import annotations

import math
import sqlite3
import time as _time
from typing import Any

from cerebrofy.config.loader import MemoryConfig
from cerebrofy.memory.store import Memory, _SELECT_COLS, row_to_memory


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


def _recompute_rows(
    conn: sqlite3.Connection,
    rows: list[tuple[Any, ...]],
    changed_neuron_ids: set[str],
    current_ts: int,
    config: MemoryConfig,
) -> int:
    """Recompute decay for a list of memory rows. Returns count of changed rows."""
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


def recompute_all_decay(
    conn: sqlite3.Connection,
    changed_neuron_ids: set[str],
    config: MemoryConfig,
) -> int:
    """Recompute decay for memories. Returns count of rows whose status changed.

    Pass empty set for build (time-decay only, all memories).
    Pass affected_node_ids for update (signature penalty for those neurons;
    time-decay only for all others). On incremental update only memories
    attached to changed neurons are fetched and recomputed in Python;
    unattached memories are updated via a bulk SQL time-decay pass.
    """
    current_ts = int(_time.time())

    if not changed_neuron_ids:
        # Full rebuild: recompute every memory in Python (no signature penalty)
        rows = conn.execute(f"SELECT {_SELECT_COLS} FROM memories").fetchall()
        return _recompute_rows(conn, rows, set(), current_ts, config)

    # Incremental update: only fetch memories attached to changed neurons
    placeholders = ",".join("?" * len(changed_neuron_ids))
    affected_rows = conn.execute(
        f"SELECT {_SELECT_COLS} FROM memories WHERE neuron_id IN ({placeholders})",
        list(changed_neuron_ids),
    ).fetchall()

    # Recompute affected memories (with signature penalty where applicable)
    changed_count = _recompute_rows(conn, affected_rows, changed_neuron_ids, current_ts, config)

    # Time-only decay for all remaining memories (not attached to changed neurons)
    unaffected_rows = conn.execute(
        f"SELECT {_SELECT_COLS} FROM memories "
        f"WHERE neuron_id NOT IN ({placeholders}) OR neuron_id IS NULL",
        list(changed_neuron_ids),
    ).fetchall()
    changed_count += _recompute_rows(conn, unaffected_rows, set(), current_ts, config)

    return changed_count
