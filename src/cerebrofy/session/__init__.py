"""Live Agent Session Recorder (Idea #11).

Records every MCP tool call of an agent session as a structured, local-only
replay: sessions + session_events in ``.cerebrofy/db/sessions.db``, with
before/after blast-radius metrics from Idea #01.
"""

from cerebrofy.session.recorder import (
    MAX_REFS_PER_EVENT,
    MAX_TRACKED_NEURONS,
    NO_ACTIVE_SESSION,
    SESSION_NOT_FOUND,
    VALID_OUTCOMES,
    SessionEvent,
    SessionNotFoundError,
    SessionRecord,
    SessionSearchHit,
    active_session,
    count_events,
    end_session,
    get_session,
    latest_session,
    list_events,
    list_sessions,
    neuron_blast_metric,
    new_session_id,
    open_sessions_db,
    record_event,
    resolve_neuron_refs,
    search_sessions,
    start_session,
    truncate_args,
    truncate_summary,
)

__all__ = [
    "MAX_REFS_PER_EVENT",
    "MAX_TRACKED_NEURONS",
    "NO_ACTIVE_SESSION",
    "SESSION_NOT_FOUND",
    "VALID_OUTCOMES",
    "SessionEvent",
    "SessionNotFoundError",
    "SessionRecord",
    "SessionSearchHit",
    "active_session",
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
]
