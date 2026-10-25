"""Session + event storage for the Live Agent Session Recorder (Idea #11).

All state lives in ``.cerebrofy/db/sessions.db`` — a database separate from
``cerebrofy.db`` for the same reason memories.db is separate (#05): the index
is rebuilt atomically by ``cerebrofy build`` and written under
``BEGIN IMMEDIATE`` by ``cerebrofy update``, while the session log must survive
rebuilds and never contend with the index writer.  Storage is local-only: no
network, no uploads.

Blast-radius metrics (#01): the first time a neuron is referenced during a
session, its depth-2 caller count is captured ("before"); at session end the
same metric is recomputed for the tracked set ("after").  Per-neuron lookups are
deduplicated and the tracked set is capped at ``MAX_TRACKED_NEURONS`` so the
per-tool-call recording overhead stays bounded.

─── Facade over ``_recorder/`` package ─────────────────────────────────────
This module is a thin re-export facade.  The implementation was split into the
private ``cerebrofy.session._recorder`` sub-modules for maintainability (m9):

* ``models.py``     — dataclasses + SessionNotFoundError
* ``args.py``       — redaction/truncation helpers + constants
* ``schema.py``     — open_sessions_db, _SESSION_COLS, row converters
* ``queries.py``    — read queries (get_session, list_sessions, …)
* ``blast.py``      — neuron_blast_metric, resolve_neuron_refs, _track_neuron_refs
* ``lifecycle.py``  — new_session_id, start_session, record_event, end_session
* ``memory.py``     — build_session_memory, write_memory_if_possible, …

Heavy / native-backed collaborators — ``sqlite_vec`` (native C extension), the
fastembed-backed embedder, and the monkeypatch-targeted memory-store openers —
remain lazily imported inside their functions; see the inline comments in
``_recorder/schema.py``, ``_recorder/memory.py`` for why they stay lazy.
"""

from __future__ import annotations

from cerebrofy.session._recorder.args import (
    truncate_args,
    truncate_summary,
)
from cerebrofy.session._recorder.blast import (
    MAX_REFS_PER_EVENT,
    MAX_TRACKED_NEURONS,
    neuron_blast_metric,
    resolve_neuron_refs,
)
from cerebrofy.session._recorder.lifecycle import (
    VALID_OUTCOMES,
    end_session,
    new_session_id,
    record_event,
    start_session,
)
from cerebrofy.session._recorder.memory import (
    build_session_memory,
    write_memory_if_possible,
    write_session_summary_memory,
)
from cerebrofy.session._recorder.models import (
    NO_ACTIVE_SESSION,
    RECORDING_DISABLED,
    SESSION_NOT_FOUND,
    SessionEvent,
    SessionNotFoundError,
    SessionRecord,
    SessionSearchHit,
)
from cerebrofy.session._recorder.queries import (
    active_session,
    count_events,
    get_session,
    latest_session,
    list_events,
    list_sessions,
    search_sessions,
)
from cerebrofy.session._recorder.schema import open_sessions_db

__all__ = [
    "MAX_REFS_PER_EVENT",
    "MAX_TRACKED_NEURONS",
    "NO_ACTIVE_SESSION",
    "RECORDING_DISABLED",
    "SESSION_NOT_FOUND",
    "VALID_OUTCOMES",
    "SessionEvent",
    "SessionNotFoundError",
    "SessionRecord",
    "SessionSearchHit",
    "active_session",
    "build_session_memory",
    "count_events",
    "end_session",
    "get_session",
    "latest_session",
    "list_events",
    "list_sessions",
    "neuron_blast_metric",
    "new_session_id",
    "open_sessions_db",
    "record_event",
    "resolve_neuron_refs",
    "search_sessions",
    "start_session",
    "truncate_args",
    "truncate_summary",
    "write_memory_if_possible",
    "write_session_summary_memory",
]

# Re-export private helpers that were importable from this module previously.
# They remain in the sub-modules; these aliases preserve the lookup path for any
# code that imports them via ``cerebrofy.session.recorder._foo``.
