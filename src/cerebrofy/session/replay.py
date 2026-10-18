"""Session replay + graph-diff generation (Idea #11).

``build_session_diff`` answers "what did this session do to the graph?" from the
data the recorder captured: the neurons it touched, which of them still exist,
which references only became resolvable after an index refresh, and whether the
session's own build/update calls changed the graph mid-session.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from cerebrofy.session.recorder import (
    SessionEvent,
    SessionRecord,
    count_events,
    get_session,
    latest_session,
    list_events,
    neuron_blast_metric,
    resolve_neuron_refs,
)

# Tools that rewrite the index — a session containing one of these changed the
# graph mid-session, so "before" metrics describe the pre-refresh graph.
GRAPH_REFRESH_TOOLS: frozenset[str] = frozenset({"cerebrofy_build", "cerebrofy_update"})


@dataclass(frozen=True)
class SessionDiff:
    """Graph delta observed across a recorded session."""

    touched: tuple[str, ...]
    present: tuple[str, ...]
    missing: tuple[str, ...]
    appeared: tuple[str, ...]
    graph_refreshed: bool
    blast_radius_before: int | None
    blast_radius_after: int | None

    @property
    def blast_delta(self) -> int | None:
        """after − before; None when either metric is unknown."""
        if self.blast_radius_before is None or self.blast_radius_after is None:
            return None
        return self.blast_radius_after - self.blast_radius_before

    @property
    def risk_verdict(self) -> str:
        """Human-readable blast-radius verdict for reports."""
        delta = self.blast_delta
        if delta is None:
            return "unknown"
        if delta > 0:
            return "increased"
        if delta < 0:
            return "decreased"
        return "unchanged"


def neuron_label(node_id: str) -> str:
    """Short display label for a node id (``file::name`` → ``name``)."""
    return node_id.rsplit("::", 1)[-1]


def build_session_diff(
    session: SessionRecord,
    events: list[SessionEvent],
    index_conn: sqlite3.Connection | None = None,
) -> SessionDiff:
    """Compute the session's graph delta (best effort when the index is absent)."""
    touched = session.neurons_touched
    present: list[str] = []
    missing: list[str] = []
    if index_conn is not None:
        for node_id in touched:
            if neuron_blast_metric(index_conn, node_id) is None:
                missing.append(node_id)
            else:
                present.append(node_id)
    else:
        present = list(touched)

    appeared: list[str] = []
    if index_conn is not None:
        tracked = set(touched)
        for event in events:
            for node_id in resolve_neuron_refs(index_conn, event.args):
                if node_id not in tracked and node_id not in appeared:
                    appeared.append(node_id)

    refreshed = any(event.tool in GRAPH_REFRESH_TOOLS for event in events)
    return SessionDiff(
        touched=touched,
        present=tuple(present),
        missing=tuple(missing),
        appeared=tuple(appeared),
        graph_refreshed=refreshed,
        blast_radius_before=session.blast_radius_before,
        blast_radius_after=session.blast_radius_after,
    )


def replay_session(
    conn: sqlite3.Connection,
    session_id: str | None = None,
    *,
    index_conn: sqlite3.Connection | None = None,
) -> tuple[SessionRecord, list[SessionEvent], SessionDiff]:
    """Load a session (default: the latest) plus its events and graph diff.

    TODO(integration-17): the AI review copilot will consume this replay as
    pre-review context for AI-authored changes.
    """
    from cerebrofy.session.recorder import SessionNotFoundError

    session = get_session(conn, session_id) if session_id else latest_session(conn)
    if session is None:
        raise SessionNotFoundError(session_id or "<latest>")
    events = list_events(conn, session.id)
    diff = build_session_diff(session, events, index_conn)
    return session, events, diff


def session_to_dict(
    session: SessionRecord,
    events: list[SessionEvent],
    diff: SessionDiff | None = None,
) -> dict[str, Any]:
    """JSON-ready view of a session (the MCP ``cerebrofy_session_show`` payload)."""
    payload: dict[str, Any] = {
        "session_id": session.id,
        "task": session.task,
        "agent": session.agent,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "duration_seconds": session.duration_seconds,
        "outcome": session.outcome,
        "outcome_notes": session.outcome_notes,
        "event_count": session.event_count,
        "neurons_touched": list(session.neurons_touched),
        "blast_radius_before": session.blast_radius_before,
        "blast_radius_after": session.blast_radius_after,
        "blast_radius_delta": session.blast_radius_delta,
        "events": [
            {
                "ts": event.ts,
                "tool": event.tool,
                "args": event.args,
                "result_summary": event.result_summary,
            }
            for event in events
        ],
    }
    if diff is not None:
        payload["diff"] = {
            "present": list(diff.present),
            "missing": list(diff.missing),
            "appeared": list(diff.appeared),
            "graph_refreshed": diff.graph_refreshed,
            "risk_verdict": diff.risk_verdict,
        }
    return payload


def session_summary_line(conn: sqlite3.Connection, session: SessionRecord) -> str:
    """One-line summary used by the CLI list view header."""
    return (
        f"{session.id}  {session.task}  "
        f"({count_events(conn, session.id)} events, outcome={session.outcome})"
    )
