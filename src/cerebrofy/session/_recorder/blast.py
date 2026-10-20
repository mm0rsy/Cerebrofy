"""Blast-radius metrics and neuron reference tracking (Idea #01).

Captures the depth-2 caller count for neurons referenced during a session,
"before" the first mention and "after" session end.  Per-neuron lookups are
deduplicated and the tracked set is capped at ``MAX_TRACKED_NEURONS`` so the
per-tool-call recording overhead stays bounded.

Split from ``recorder.py`` (m9 maintainability split).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Mapping
from typing import Any

from cerebrofy.analysis.blast_radius import bfs_callers, neuron_for_target
from cerebrofy.config.loader import SessionConfig

# Re-exported logger name preserved for caplog-based tests that assert on
# ``cerebrofy.session.recorder``.
_logger = logging.getLogger("cerebrofy.session.recorder")

# Bounding constants for the blast-radius tracking (overhead control).
# Their default values originate from ``cerebrofy.config.loader.SessionConfig``
# (which reads ``.cerebrofy/config.yaml``) so the knobs are configurable.  They
# are retained as module-level constants for backward compatibility (re-exported
# via ``cerebrofy.session``); new callers should pass the explicit keyword-only
# ``max_tracked_neurons`` / ``max_refs_per_event`` params on record_event()
# instead of depending on these defaults.
MAX_TRACKED_NEURONS: int = SessionConfig().max_tracked_neurons  # 50
MAX_REFS_PER_EVENT: int = SessionConfig().max_refs_per_event    # 3
_MAX_FILE_REFS = 5

# Thread-safe lock for session database updates (race condition fix).
_SESSION_LOCK = threading.Lock()


def neuron_blast_metric(
    index_conn: sqlite3.Connection, neuron_id: str, *, depth: int = 2
) -> int | None:
    """Depth-1 + depth-2 caller count for *neuron_id*; None when not in the index.

    Mirrors ``analysis.blast_radius.bfs_callers`` (RUNTIME_BOUNDARY edges are
    never traversed — Law II).
    """
    try:
        row = index_conn.execute(
            "SELECT 1 FROM nodes WHERE id = ? LIMIT 1", (neuron_id,)
        ).fetchone()
        if row is None:
            return None
        d1, d2, _boundaries = bfs_callers(neuron_id, index_conn, max_depth=depth)
        return len(d1) + len(d2)
    except sqlite3.Error:
        return None


def resolve_neuron_refs(
    index_conn: sqlite3.Connection,
    args: Mapping[str, Any],
    *,
    limit: int = MAX_REFS_PER_EVENT,
) -> list[str]:
    """Resolve neuron references inside tool *args* to node ids (best effort).

    Recognised keys: ``target`` / ``neuron`` / ``name`` (a neuron reference
    accepted by ``analysis.blast_radius.neuron_for_target``) and ``file`` /
    ``path`` (all non-module neurons defined in that file, capped).
    """
    refs: list[str] = []

    def _add(node_id: str | None) -> None:
        if node_id and not node_id.startswith("external::") and node_id not in refs:
            refs.append(node_id)

    for key in ("target", "neuron", "name"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            try:
                neuron = neuron_for_target(value.strip(), index_conn)
            except sqlite3.Error:
                neuron = None
            _add(neuron.id if neuron is not None else None)

    for key in ("file", "path"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            try:
                rows = index_conn.execute(
                    "SELECT id FROM nodes WHERE file = ? AND type != 'module' LIMIT ?",
                    (value.strip(), _MAX_FILE_REFS),
                ).fetchall()
            except sqlite3.Error:
                rows = []
            for (node_id,) in rows:
                _add(str(node_id))

    return refs[:limit]


def _track_neuron_refs(
    conn: sqlite3.Connection,
    session_id: str,
    args: dict[str, Any],
    index_conn: sqlite3.Connection,
    *,
    max_tracked_neurons: int,
    max_refs_per_event: int,
) -> None:
    """Fold newly-referenced neurons into ``neurons_touched`` / ``blast_radius_before``.

    This function acquires the global ``_SESSION_LOCK`` to serialise the
    read-modify-write on the session row, preventing lost updates when
    concurrent tool calls touch the same session.

    *max_tracked_neurons* caps the total number of neurons recorded for the
    session (bounding blast-radius lookup cost); *max_refs_per_event* caps how
    many neuron references a single event may resolve.  Both flow from
    :func:`record_event` (whose defaults are the SessionConfig-backed module
    constants) so callers can override the bounds without touching module state.
    """
    with _SESSION_LOCK:
        row = conn.execute(
            "SELECT neurons_touched, blast_radius_before FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return
        try:
            touched_raw = json.loads(row[0]) if row[0] else []
        except (json.JSONDecodeError, TypeError):
            # Corrupted/malformed session JSON must never break a write path.
            _logger.warning(
                "corrupt neurons_touched JSON while tracking refs for session '%s'; "
                "falling back to empty", session_id,
            )
            touched_raw = []
        touched: list[str] = [
            str(x) for x in touched_raw
        ] if isinstance(touched_raw, list) else []
        if len(touched) >= max_tracked_neurons:
            return

        before: int | None = int(row[1]) if row[1] is not None else None
        changed = False
        for node_id in resolve_neuron_refs(index_conn, args, limit=max_refs_per_event):
            if node_id in touched:
                continue
            metric = neuron_blast_metric(index_conn, node_id)
            if metric is None:
                continue
            touched.append(node_id)
            before = (before or 0) + metric
            changed = True
            if len(touched) >= max_tracked_neurons:
                break

        if changed:
            conn.execute(
                "UPDATE sessions SET neurons_touched = ?, blast_radius_before = ? WHERE id = ?",
                (json.dumps(touched), before, session_id),
            )
