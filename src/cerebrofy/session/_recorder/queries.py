"""Read queries for the session recorder (Idea #11).

All functions accept an open ``sqlite3.Connection`` and return dataclasses.
Row converters live in :mod:`cerebrofy.session._recorder.schema` and are
re-used here so the SQL column order stays in one place.

Split from ``recorder.py`` (m9 maintainability split).
"""

from __future__ import annotations

import json
import sqlite3

from cerebrofy.session._recorder.models import SessionEvent, SessionRecord, SessionSearchHit
from cerebrofy.session._recorder.schema import _SESSION_COLS, _row_to_event, _row_to_session


def get_session(conn: sqlite3.Connection, session_id: str) -> SessionRecord | None:
    """Return a session by id, or None."""
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_session(row) if row else None


def latest_session(conn: sqlite3.Connection) -> SessionRecord | None:
    """Return the most recently started session, or None."""
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return _row_to_session(row) if row else None


def active_session(conn: sqlite3.Connection) -> SessionRecord | None:
    """Return the most recent still-open session, or None."""
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions WHERE ended_at IS NULL "
        f"ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return _row_to_session(row) if row else None


def list_sessions(conn: sqlite3.Connection, *, limit: int = 20) -> list[SessionRecord]:
    """Return sessions newest-first, capped at *limit*."""
    rows = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions "
        f"ORDER BY started_at DESC, rowid DESC LIMIT ?",
        (max(1, limit),),
    ).fetchall()
    return [_row_to_session(r) for r in rows]


def list_events(conn: sqlite3.Connection, session_id: str) -> list[SessionEvent]:
    """Return the events of a session in recording order.

    TODO(integration-21): the insight daemon will tail this stream to emit
    session_pattern insights; keep the (session_id, id) index for that reader.
    """
    rows = conn.execute(
        "SELECT session_id, ts, tool, args, result_summary FROM session_events "
        "WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def count_events(conn: sqlite3.Connection, session_id: str) -> int:
    """Return the number of events recorded for a session."""
    row = conn.execute(
        "SELECT COUNT(*) FROM session_events WHERE session_id = ?", (session_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def search_sessions(
    conn: sqlite3.Connection,
    query_text: str,
    *,
    query_embedding: list[float] | None = None,
    limit: int = 10,
) -> list[SessionSearchHit]:
    """Search recorded sessions by task text.

    Semantic KNN over ``vec_sessions`` when *query_embedding* is given
    (embeddings produced by ``cerebrofy.search.hybrid.embed_query``); otherwise
    falls back to a case-insensitive substring match over task text so search
    still works when embeddings are disabled.
    """
    if query_embedding is not None:
        oversample_k = max(limit * 20, 100)
        vec_rows = conn.execute(
            "SELECT rowid, distance FROM vec_sessions "
            "WHERE embedding MATCH vec_f32(?) AND k = ?",
            (json.dumps(query_embedding), oversample_k),
        ).fetchall()
        if not vec_rows:
            return []
        distances = {int(r[0]): float(r[1]) for r in vec_rows}
        placeholders = ",".join("?" * len(distances))
        rows = conn.execute(
            f"SELECT rowid, {_SESSION_COLS} FROM sessions WHERE rowid IN ({placeholders})",
            list(distances.keys()),
        ).fetchall()
        hits = [
            SessionSearchHit(
                session=_row_to_session(r[1:]),
                score=round(max(0.0, 1.0 - (distances[int(r[0])] ** 2) / 2.0), 4),
                match_kind="semantic",
            )
            for r in rows
        ]
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    if not query_text.strip():
        return []
    rows = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions "
        f"WHERE task LIKE ? ORDER BY started_at DESC LIMIT ?",
        (f"%{query_text.strip()}%", max(1, limit)),
    ).fetchall()
    return [
        SessionSearchHit(session=_row_to_session(r), score=0.0, match_kind="task_text")
        for r in rows
    ]
