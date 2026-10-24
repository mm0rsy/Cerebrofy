"""Session lifecycle: create, record events, and close (Idea #11).

This sub-module owns the write path — ``start_session``, ``record_event``, and
``end_session``.  Read-side helpers live in :mod:`cerebrofy.session._recorder.queries`.

Split from ``recorder.py`` (m9 maintainability split).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from cerebrofy.session._recorder.args import truncate_args, truncate_summary
from cerebrofy.session._recorder.blast import (
    MAX_REFS_PER_EVENT,
    MAX_TRACKED_NEURONS,
    _track_neuron_refs,
    neuron_blast_metric,
)
from cerebrofy.session._recorder.memory import write_session_summary_memory
from cerebrofy.session._recorder.models import SessionEvent, SessionNotFoundError, SessionRecord
from cerebrofy.session._recorder.queries import get_session

# Re-exported logger name preserved for caplog-based tests that assert on
# ``cerebrofy.session.recorder``.
_logger = logging.getLogger("cerebrofy.session.recorder")

# Allowed session-outcome values, ordered by the severity ladder used in
# reports (success -> partial -> failed -> unknown).  end_session() lower-cases
# and strips any user-supplied outcome before testing membership, so ``in``
# checks still work; the error message uses sorted() + ', '.join() which is
# identical for a tuple.  Kept as a tuple (not frozenset) so the allowed set is
# ordered and self-documenting.
VALID_OUTCOMES: tuple[str, ...] = (
    "success",
    "partial",
    "failed",
    "unknown",
)

_SESSION_ID_PREFIX = "sess_"


def _trigger_synthesis(cerebrofy_dir: Path) -> None:
    """M4: run the synthesizer on session boundaries without ever raising."""
    try:
        from cerebrofy.synthesizer.analyzer import maybe_run_synthesis, synthesis_interval

        maybe_run_synthesis(
            cerebrofy_dir, every_n=synthesis_interval(cerebrofy_dir)
        )
    except Exception:
        # Never let the reflection loop fail a session close.
        _logger.warning("cross-session synthesis skipped", exc_info=True)


def new_session_id() -> str:
    """Return a fresh, collision-resistant session id (``sess_<hex8>``)."""
    return f"{_SESSION_ID_PREFIX}{uuid.uuid4().hex[:8]}"


def start_session(
    conn: sqlite3.Connection,
    *,
    task: str,
    agent: str | None = None,
    now: int | None = None,
    embedding: list[float] | None = None,
) -> SessionRecord:
    """Insert a new open session. When *embedding* is given, index it for search."""
    session_id = new_session_id()
    ts = int(now if now is not None else time.time())
    conn.execute(
        "INSERT INTO sessions(id, started_at, agent, task, outcome, neurons_touched) "
        "VALUES (?,?,?,?,?,?)",
        (session_id, ts, agent, task, "unknown", "[]"),
    )
    if embedding is not None:
        rowid = conn.execute(
            "SELECT rowid FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if rowid is not None:
            conn.execute(
                "INSERT INTO vec_sessions(rowid, embedding) VALUES (?, vec_f32(?))",
                (int(rowid[0]), json.dumps(embedding)),
            )
    conn.commit()
    session = get_session(conn, session_id)
    assert session is not None  # inserted above
    return session


def record_event(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    tool: str,
    args: Mapping[str, Any] | None = None,
    result_summary: str | None = None,
    ts: int | None = None,
    index_conn: sqlite3.Connection | None = None,
    max_tracked_neurons: int = MAX_TRACKED_NEURONS,
    max_refs_per_event: int = MAX_REFS_PER_EVENT,
) -> SessionEvent:
    """Append one tool-call event, bumping the session's event counter.

    When *index_conn* is provided, neuron references in *args* are resolved and
    their depth-2 caller counts are folded into ``blast_radius_before`` the
    first time each neuron is seen in this session.

    *max_tracked_neurons* (default ``MAX_TRACKED_NEURONS`` / ``SessionConfig``)
    bounds the total number of neurons tracked per session, and
    *max_refs_per_event* (default ``MAX_REFS_PER_EVENT`` / ``SessionConfig``)
    bounds how many neuron references a single event may resolve.  Omitting both
    preserves the existing behavior.
    """
    event_args = truncate_args(args or {})
    summary = truncate_summary(result_summary)
    event_ts = int(ts if ts is not None else time.time())
    conn.execute(
        "INSERT INTO session_events(session_id, ts, tool, args, result_summary) "
        "VALUES (?,?,?,?,?)",
        (session_id, event_ts, tool, json.dumps(event_args), summary),
    )
    conn.execute(
        "UPDATE sessions SET event_count = event_count + 1 WHERE id = ?", (session_id,)
    )
    if index_conn is not None:
        _track_neuron_refs(
            conn, session_id, event_args, index_conn,
            max_tracked_neurons=max_tracked_neurons,
            max_refs_per_event=max_refs_per_event,
        )
    conn.commit()
    return SessionEvent(
        session_id=session_id, ts=event_ts, tool=tool,
        args=event_args, result_summary=summary,
    )


def end_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    outcome: str | None = None,
    notes: str | None = None,
    now: int | None = None,
    index_conn: sqlite3.Connection | None = None,
    cerebrofy_dir: Path | None = None,
    embed_memory_fn: Callable[[str, str], list[float]] | None = None,
) -> SessionRecord:
    """Close a session: set ended_at / outcome / notes and the after-metric.

    ``outcome`` defaults to ``"unknown"``; an unknown value raises ValueError.
    When *index_conn* is provided and neurons were tracked, ``blast_radius_after``
    is recomputed over the tracked set against the current index.

    When *cerebrofy_dir* is provided (MCP/CLI context), the closed session is
    also folded into the #05 memory layer as a single decision memory via
    :func:`write_session_summary_memory` — the Phase 2 loop #11 -> #05 -> #11.
    This step is non-fatal: a memory-store failure never masks a closed session.
    *embed_memory_fn* is forwarded to :func:`write_session_summary_memory` to
    override the default embedder (defaults to the current import when omitted).

    TODO(integration-24): the cross-session synthesizer will read closed
    sessions (outcome + outcome_notes) from this table to detect patterns.
    """
    session = get_session(conn, session_id)
    if session is None:
        raise SessionNotFoundError(session_id)

    if session.ended_at is not None:
        raise ValueError(f"session '{session_id}' already ended")

    outcome_value = (outcome or "unknown").strip().lower() or "unknown"
    if outcome_value not in VALID_OUTCOMES:
        raise ValueError(
            f"invalid outcome '{outcome}'. Valid: {', '.join(sorted(VALID_OUTCOMES))}"
        )

    after: int | None = None
    if index_conn is not None and session.neurons_touched:
        total = 0
        present = 0
        for node_id in session.neurons_touched:
            metric = neuron_blast_metric(index_conn, node_id)
            if metric is not None:
                total += metric
                present += 1
        after = total if present else None

    ts = int(now if now is not None else time.time())
    # Use COALESCE for after only when it's not None; otherwise set explicitly
    if after is not None:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, outcome = ?, outcome_notes = ?, "
            "blast_radius_after = ? WHERE id = ?",
            (ts, outcome_value, notes, after, session_id),
        )
    else:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, outcome = ?, outcome_notes = ?, "
            "blast_radius_after = NULL WHERE id = ?",
            (ts, outcome_value, notes, session_id),
        )
    conn.commit()
    updated = get_session(conn, session_id)
    assert updated is not None  # session existed above
    if cerebrofy_dir is not None:
        # Phase 2 loop (#11 -> #05 -> #11): summarise the closed session as a
        # decision memory.  Non-fatal — never let the memory layer fail a close.
        write_session_summary_memory(
            cerebrofy_dir, updated, embed_memory_fn=embed_memory_fn
        )
        _trigger_synthesis(cerebrofy_dir)
    return updated
