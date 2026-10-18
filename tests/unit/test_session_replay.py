"""Unit tests for cerebrofy.session.replay (Idea #11)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrofy.db.schema import create_schema
from cerebrofy.session.recorder import (
    SessionEvent,
    SessionNotFoundError,
    SessionRecord,
    end_session,
    list_events,
    open_sessions_db,
    record_event,
    start_session,
)
from cerebrofy.session.replay import (
    build_session_diff,
    neuron_label,
    replay_session,
    session_summary_line,
    session_to_dict,
)


def _make_index(tmp_path: Path) -> sqlite3.Connection:
    (tmp_path / ".cerebrofy" / "db").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(tmp_path / ".cerebrofy" / "db" / "cerebrofy.db")
    create_schema(conn, embed_dim=0)
    conn.execute(
        "INSERT INTO nodes VALUES ('a.py::hub','hub','a.py','function',1,5,NULL,NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('a.py::caller','caller','a.py','function',7,9,NULL,NULL,NULL)"
    )
    conn.execute("INSERT INTO edges VALUES ('a.py::caller','a.py::hub','LOCAL_CALL','a.py')")
    conn.commit()
    return conn


def _make_sessions(tmp_path: Path) -> sqlite3.Connection:
    (tmp_path / ".cerebrofy" / "db").mkdir(parents=True, exist_ok=True)
    return open_sessions_db(tmp_path / ".cerebrofy")


def test_build_session_diff_lists_present_touched(
    tmp_path: Path,
) -> None:
    index = _make_index(tmp_path)
    sessions = _make_sessions(tmp_path)
    session = start_session(sessions, task="T", now=1000)
    record_event(sessions, session.id, tool="cerebrofy_impact",
                 args={"target": "hub"}, ts=1001, index_conn=index)
    session = end_session(sessions, session.id, now=1010, index_conn=index)
    events: list[SessionEvent] = []

    diff = build_session_diff(session, events, index)
    assert diff.present == ("a.py::hub",)
    assert diff.missing == ()
    assert diff.graph_refreshed is False
    assert diff.blast_delta == 0
    assert diff.risk_verdict == "unchanged"
    index.close()
    sessions.close()


def test_build_session_diff_flags_removed_and_appeared(tmp_path: Path) -> None:
    index = _make_index(tmp_path)
    sessions = _make_sessions(tmp_path)
    session = start_session(sessions, task="T", now=1000)
    record_event(sessions, session.id, tool="cerebrofy_impact",
                 args={"target": "hub"}, ts=1001, index_conn=index)
    # The session adds a new neuron and removes the tracked one.
    index.execute("DELETE FROM nodes WHERE id = 'a.py::hub'")
    index.execute("DELETE FROM edges")
    index.execute(
        "INSERT INTO nodes VALUES ('b.py::new','new','b.py','function',1,1,NULL,NULL,NULL)"
    )
    index.commit()
    events = [
        SessionEvent(session_id=session.id, ts=1005, tool="cerebrofy_update",
                     args={"path": "b.py"}, result_summary=None),
    ]

    session = end_session(sessions, session.id, now=1010, index_conn=index)
    diff = build_session_diff(session, events, index)
    assert diff.missing == ("a.py::hub",)
    assert diff.appeared == ("b.py::new",)
    assert diff.graph_refreshed is True
    index.close()
    sessions.close()


def test_build_session_diff_without_index_is_best_effort(tmp_path: Path) -> None:
    sessions = _make_sessions(tmp_path)
    session = start_session(sessions, task="T", now=1000)
    diff = build_session_diff(session, [], None)
    assert diff.present == diff.touched
    assert diff.appeared == ()
    assert diff.blast_delta is None
    assert diff.risk_verdict == "unknown"
    sessions.close()


def test_risk_verdict_uses_recorded_metrics(tmp_path: Path) -> None:
    """Verdict reflects the before/after metrics frozen at session end."""
    index = _make_index(tmp_path)
    sessions = _make_sessions(tmp_path)
    session = start_session(sessions, task="T", now=1000)
    record_event(sessions, session.id, tool="cerebrofy_impact",
                 args={"target": "hub"}, ts=1001, index_conn=index)
    index.execute(
        "INSERT INTO nodes VALUES ('b.py::new','new','b.py','function',1,1,NULL,NULL,NULL)"
    )
    index.execute("INSERT INTO edges VALUES ('b.py::new','a.py::hub','LOCAL_CALL','b.py')")
    index.commit()
    session = end_session(sessions, session.id, now=1010, index_conn=index)
    assert build_session_diff(session, [], index).risk_verdict == "increased"

    # Later graph edits do not rewrite a finished session's recorded metrics.
    index.execute("DELETE FROM edges WHERE src_id = 'b.py::new'")
    index.commit()
    assert build_session_diff(session, [], index).risk_verdict == "increased"
    index.close()
    sessions.close()


def test_risk_verdict_decreased_unchanged_unknown() -> None:
    def record(before: int | None, after: int | None) -> SessionRecord:
        return SessionRecord(
            id="sess_x",
            task="T",
            agent=None,
            started_at=0,
            ended_at=1,
            outcome="unknown",
            outcome_notes=None,
            neurons_touched=("a.py::hub",),
            blast_radius_before=before,
            blast_radius_after=after,
            event_count=1,
        )

    assert build_session_diff(record(3, 1), [], None).risk_verdict == "decreased"
    assert build_session_diff(record(2, 2), [], None).risk_verdict == "unchanged"
    assert build_session_diff(record(None, 2), [], None).risk_verdict == "unknown"
    assert build_session_diff(record(2, None), [], None).risk_verdict == "unknown"


def test_replay_session_uses_latest_by_default(tmp_path: Path) -> None:
    sessions = _make_sessions(tmp_path)
    first = start_session(sessions, task="first", now=1000)
    end_session(sessions, first.id, now=1001)
    second = start_session(sessions, task="second", now=2000)
    record_event(sessions, second.id, tool="search_code", args={"query": "x"}, ts=2001)

    session, events, diff = replay_session(sessions)
    assert session.id == second.id
    assert len(events) == 1
    assert diff.graph_refreshed is False


def test_replay_session_raises_for_unknown_id(tmp_path: Path) -> None:
    sessions = _make_sessions(tmp_path)
    with pytest.raises(SessionNotFoundError):
        replay_session(sessions, "sess_nope")
    with pytest.raises(SessionNotFoundError):
        replay_session(sessions)
    sessions.close()


def test_session_to_dict_payload_shape(tmp_path: Path) -> None:
    sessions = _make_sessions(tmp_path)
    session = start_session(sessions, task="Add rate limiting", agent="claude", now=1000)
    record_event(sessions, session.id, tool="search_code",
                 args={"query": "login"}, result_summary="3 hits", ts=1001)
    session = end_session(sessions, session.id, outcome="success", notes="done", now=1060)
    events = list_events(sessions, session.id)
    diff = build_session_diff(session, events, None)

    payload = session_to_dict(session, events, diff)
    assert payload["session_id"] == session.id
    assert payload["task"] == "Add rate limiting"
    assert payload["agent"] == "claude"
    assert payload["duration_seconds"] == 60
    assert payload["outcome"] == "success"
    assert payload["outcome_notes"] == "done"
    assert payload["events"][0]["tool"] == "search_code"
    assert payload["events"][0]["args"] == {"query": "login"}
    assert payload["diff"]["risk_verdict"] == "unknown"
    sessions.close()


def test_neuron_label() -> None:
    assert neuron_label("src/a.py::do_thing") == "do_thing"
    assert neuron_label("do_thing") == "do_thing"


def test_session_summary_line(tmp_path: Path) -> None:
    sessions = _make_sessions(tmp_path)
    session = start_session(sessions, task="T", now=1000)
    record_event(sessions, session.id, tool="x", ts=1)
    line = session_summary_line(sessions, session)
    assert session.id in line
    assert "1 events" in line
    sessions.close()
