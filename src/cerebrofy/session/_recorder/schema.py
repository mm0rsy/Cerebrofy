"""Schema creation, connection management, and row converters (Idea #11).

This sub-module owns the sessions.db connection lifecycle and the row → dataclass
converters.  It was split from ``recorder.py`` (m9 maintainability split).

``sqlite_vec`` (a native C extension) is imported lazily by
``cerebrofy.db.vec.load_sqlite_vec`` (called from ``open_sessions_db``) so that
importing this module — which ``cerebrofy.commands.session`` imports
unconditionally for *every* CLI command — stays free of native-load cost. The
version guard that used to live inline is now centralized there.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cerebrofy.db.schema import create_session_schema
from cerebrofy.db.vec import load_sqlite_vec
from cerebrofy.session._recorder.models import SessionEvent, SessionRecord

# Re-exported logger name preserved for caplog-based tests that assert on
# ``cerebrofy.session.recorder``.
_logger = logging.getLogger("cerebrofy.session.recorder")

# Column projection shared by every read query.  Order is significant: the
# row converters below index by position.
_SESSION_COLS = (
    "id, started_at, ended_at, agent, task, outcome, outcome_notes, "
    "neurons_touched, blast_radius_before, blast_radius_after, event_count"
)


def open_sessions_db(cerebrofy_dir: Path) -> sqlite3.Connection:
    """Open (or create) sessions.db, load sqlite-vec, apply the schema idempotently."""
    db_path = cerebrofy_dir / "db" / "sessions.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the MCP middleware may touch this connection from
    # an SDK worker thread; access stays serialized in practice.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    load_sqlite_vec(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    create_session_schema(conn)
    return conn


def _row_to_session(row: Sequence[Any]) -> SessionRecord:
    """Convert a raw SELECT row into a :class:`SessionRecord`."""
    touched_raw = row[7]
    touched: tuple[str, ...] = ()
    if touched_raw:
        try:
            loaded = json.loads(touched_raw)
            if isinstance(loaded, list):
                touched = tuple(str(item) for item in loaded)
        except (json.JSONDecodeError, TypeError):
            # Corrupted/malformed session JSON must never break a read path.
            _logger.warning(
                "corrupt neurons_touched JSON for session '%s'; "
                "falling back to empty", row[0],
            )
            touched = ()
    return SessionRecord(
        id=str(row[0]),
        started_at=int(row[1]),
        ended_at=int(row[2]) if row[2] is not None else None,
        agent=row[3],
        task=str(row[4]),
        outcome=str(row[5] or "unknown"),
        outcome_notes=row[6],
        neurons_touched=touched,
        blast_radius_before=int(row[8]) if row[8] is not None else None,
        blast_radius_after=int(row[9]) if row[9] is not None else None,
        event_count=int(row[10] or 0),
    )


def _row_to_event(row: Sequence[Any]) -> SessionEvent:
    """Convert a raw SELECT row into a :class:`SessionEvent`."""
    args: dict[str, Any] = {}
    if row[3]:
        try:
            loaded = json.loads(row[3])
            if isinstance(loaded, dict):
                args = loaded
        except (json.JSONDecodeError, TypeError):
            # Corrupted/malformed session JSON must never break a read path.
            _logger.warning(
                "corrupt args JSON for session event (session_id='%s', tool='%s'); "
                "falling back to empty", row[0], row[2],
            )
            args = {}
    return SessionEvent(
        session_id=str(row[0]),
        ts=int(row[1]),
        tool=str(row[2]),
        args=args,
        result_summary=row[4],
    )
