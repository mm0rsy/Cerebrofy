"""Unit tests for cerebrofy.session.recorder (Idea #11)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cerebrofy.db.schema import create_schema
from cerebrofy.session.recorder import (
    SESSION_NOT_FOUND,
    VALID_OUTCOMES,
    SessionNotFoundError,
    SessionRecord,
    active_session,
    build_session_memory,
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
    write_memory_if_possible,
    write_session_summary_memory,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _cerebrofy_dir(tmp_path: Path) -> Path:
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True, exist_ok=True)
    return cerebrofy_dir


def _make_index(cerebrofy_dir: Path) -> sqlite3.Connection:
    """Tiny index: leaf → caller → caller2 → hub chain (hub has 3 callers)."""
    conn = sqlite3.connect(cerebrofy_dir / "db" / "cerebrofy.db")
    create_schema(conn, embed_dim=0)
    conn.execute(
        "INSERT INTO nodes VALUES ('a.py::hub','hub','a.py','function',1,5,'def hub()','',NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('a.py::caller','caller','a.py','function',7,9,'def caller()','',NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('a.py::caller2','caller2','a.py','function',10,12,'def c2()','',NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('b.py::leaf','leaf','b.py','function',1,3,'def leaf()','',NULL)"
    )
    conn.execute(
        "INSERT INTO edges VALUES ('a.py::caller','a.py::hub','LOCAL_CALL','a.py')"
    )
    conn.execute(
        "INSERT INTO edges VALUES ('a.py::caller2','a.py::caller','LOCAL_CALL','a.py')"
    )
    conn.execute(
        "INSERT INTO edges VALUES ('b.py::leaf','a.py::hub','LOCAL_CALL','b.py')"
    )
    conn.commit()
    return conn


@pytest.fixture()
def sessions_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = open_sessions_db(_cerebrofy_dir(tmp_path))
    yield conn
    conn.close()


@pytest.fixture()
def index_conn(tmp_path: Path) -> sqlite3.Connection:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    conn = _make_index(cerebrofy_dir)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Schema / connection
# ---------------------------------------------------------------------------

def test_open_sessions_db_creates_tables_and_is_idempotent(tmp_path: Path) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    first = open_sessions_db(cerebrofy_dir)
    names = {
        row[0]
        for row in first.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"sessions", "session_events", "vec_sessions"} <= names
    first.close()

    # Re-opening must not raise (upgrade path: schema applied idempotently).
    second = open_sessions_db(cerebrofy_dir)
    cols = [row[1] for row in second.execute("PRAGMA table_info(sessions)")]
    assert "outcome" in cols
    assert "outcome_notes" in cols
    second.close()


def test_open_sessions_db_creates_missing_db_directory(tmp_path: Path) -> None:
    conn = open_sessions_db(tmp_path / ".cerebrofy")
    assert (tmp_path / ".cerebrofy" / "db" / "sessions.db").exists()
    conn.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_start_session_inserts_open_session(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="Add rate limiting", agent="claude", now=1000)
    assert session.id.startswith("sess_")
    assert session.task == "Add rate limiting"
    assert session.agent == "claude"
    assert session.started_at == 1000
    assert session.ended_at is None
    assert session.outcome == "unknown"
    assert session.neurons_touched == ()
    assert session.event_count == 0
    assert session.is_active


def test_new_session_id_is_unique() -> None:
    assert new_session_id() != new_session_id()
    assert new_session_id().startswith("sess_")


def test_record_event_appends_in_order(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    record_event(sessions_conn, session.id, tool="search_code",
                 args={"query": "hub"}, result_summary="3 hits", ts=1001)
    record_event(sessions_conn, session.id, tool="get_neuron",
                 args={"name": "hub"}, result_summary=None, ts=1002)

    events = list_events(sessions_conn, session.id)
    assert [e.tool for e in events] == ["search_code", "get_neuron"]
    assert events[0].args == {"query": "hub"}
    assert events[0].result_summary == "3 hits"
    assert count_events(sessions_conn, session.id) == 2
    assert get_session(sessions_conn, session.id).event_count == 2  # type: ignore[union-attr]


def test_event_args_and_summary_are_truncated(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    record_event(
        sessions_conn, session.id, tool="search_code",
        args={"query": "x" * 1000}, result_summary=" y\n" * 400, ts=1001,
    )
    event = list_events(sessions_conn, session.id)[0]
    assert len(event.args["query"]) == 301
    assert event.args["query"].endswith("…")
    assert event.result_summary is not None
    assert len(event.result_summary) <= 501
    assert "\n" not in event.result_summary


def test_truncate_args_caps_item_count() -> None:
    args = {f"k{i}": i for i in range(50)}
    assert len(truncate_args(args)) == 20


def test_truncate_args_redacts_nested_sensitive_keys() -> None:
    args = {
        "query": "safe",
        "config": {
            "api_key": "sk-leaked",
            "nested": {"access_token": "tok-leaked", "keep": "ok"},
        },
        "data": [{"password": "p"}, {"name": "a"}],
    }
    out = truncate_args(args)
    assert out["config"]["api_key"] == "[REDACTED]"
    assert out["config"]["nested"]["access_token"] == "[REDACTED]"
    assert out["config"]["nested"]["keep"] == "ok"
    assert out["data"][0]["password"] == "[REDACTED]"
    assert out["data"][1]["name"] == "a"
    assert out["query"] == "safe"


def test_truncate_args_redacts_pattern_keys_case_insensitive() -> None:
    args = {
        "API-Key": "x",
        "Authorization": "y",
        "user_password": "z",
        "client_secret": "w",
        "Refresh-Token": "r",
    }
    out = truncate_args(args)
    assert out["API-Key"] == "[REDACTED]"
    assert out["Authorization"] == "[REDACTED]"
    assert out["user_password"] == "[REDACTED]"
    assert out["client_secret"] == "[REDACTED]"
    assert out["Refresh-Token"] == "[REDACTED]"


def test_truncate_args_redacts_sensitive_key_with_non_string_value() -> None:
    # A sensitive key's value is fully redacted regardless of its type,
    # not merely length-truncated like a regular string value.
    out = truncate_args({"api_key": {"secret": "n"}}, max_value_chars=10)
    assert out["api_key"] == "[REDACTED]"


def test_truncate_args_does_not_redact_non_sensitive_keys() -> None:
    out = truncate_args({"username": "bob", "author": "jane", "query": "q"})
    assert out == {"username": "bob", "author": "jane", "query": "q"}


def test_truncate_args_redacts_beyond_nesting_cap_instead_of_passing_raw() -> None:
    # A secret nested deeper than the recursion cap must never be persisted raw.
    payload: dict[str, object] = {}
    cursor = payload
    for _ in range(15):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    cursor["api_key"] = "sk-deep-secret"

    out = truncate_args(payload)

    def _flatten(value: object) -> str:
        if isinstance(value, dict):
            return " ".join(f"{k}={_flatten(v)}" for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return " ".join(_flatten(v) for v in value)
        return str(value)

    rendered = _flatten(out)
    assert "sk-deep-secret" not in rendered
    assert "[MAX_DEPTH]" in rendered


def test_truncate_summary_none_and_blank() -> None:
    assert truncate_summary(None) is None
    assert truncate_summary("   \n  ") is None


def test_end_session_sets_outcome_and_metrics(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    updated = end_session(
        sessions_conn, session.id, outcome="success", notes="done", now=1060
    )
    assert updated.ended_at == 1060
    assert updated.duration_seconds == 60
    assert updated.outcome == "success"
    assert updated.outcome_notes == "done"
    assert not updated.is_active


def test_end_session_defaults_outcome_to_unknown(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    assert end_session(sessions_conn, session.id, now=1001).outcome == "unknown"


def test_end_session_rejects_invalid_outcome(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    with pytest.raises(ValueError, match="invalid outcome"):
        end_session(sessions_conn, session.id, outcome="great")


def test_end_session_missing_session_raises(sessions_conn: sqlite3.Connection) -> None:
    with pytest.raises(SessionNotFoundError) as excinfo:
        end_session(sessions_conn, "sess_missing")
    assert SESSION_NOT_FOUND in str(excinfo.value)


def test_valid_outcomes_constant() -> None:
    assert VALID_OUTCOMES == {"success", "partial", "failed", "unknown"}


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def test_latest_active_and_list_sessions(sessions_conn: sqlite3.Connection) -> None:
    first = start_session(sessions_conn, task="first", now=1000)
    end_session(sessions_conn, first.id, outcome="success", now=1010)
    second = start_session(sessions_conn, task="second", now=2000)

    assert latest_session(sessions_conn).id == second.id  # type: ignore[union-attr]
    assert active_session(sessions_conn).id == second.id  # type: ignore[union-attr]
    listed = list_sessions(sessions_conn)
    assert [s.id for s in listed] == [second.id, first.id]
    assert list_sessions(sessions_conn, limit=1)[0].id == second.id


def test_get_session_returns_none_for_unknown(sessions_conn: sqlite3.Connection) -> None:
    assert get_session(sessions_conn, "sess_nope") is None
    assert latest_session(sessions_conn) is None
    assert active_session(sessions_conn) is None


# ---------------------------------------------------------------------------
# Blast-radius tracking (Idea #01)
# ---------------------------------------------------------------------------

def test_neuron_blast_metric_counts_depth2_callers(index_conn: sqlite3.Connection) -> None:
    assert neuron_blast_metric(index_conn, "a.py::hub") == 3
    assert neuron_blast_metric(index_conn, "a.py::caller") == 1
    assert neuron_blast_metric(index_conn, "a.py::caller2") == 0
    assert neuron_blast_metric(index_conn, "missing::nope") is None


def test_resolve_neuron_refs_handles_target_name_and_file(index_conn: sqlite3.Connection) -> None:
    assert resolve_neuron_refs(index_conn, {"target": "hub"}) == ["a.py::hub"]
    assert resolve_neuron_refs(index_conn, {"name": "caller"}) == ["a.py::caller"]
    assert resolve_neuron_refs(index_conn, {"path": "a.py"}) == [
        "a.py::hub", "a.py::caller", "a.py::caller2",
    ]
    assert resolve_neuron_refs(index_conn, {"path": "a.py"}, limit=1) == ["a.py::hub"]
    assert resolve_neuron_refs(index_conn, {"query": "anything"}) == []
    assert resolve_neuron_refs(index_conn, {"target": "no-such-neuron"}) == []


def test_record_event_tracks_neuron_refs_once(
    sessions_conn: sqlite3.Connection, index_conn: sqlite3.Connection
) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    record_event(sessions_conn, session.id, tool="cerebrofy_impact",
                 args={"target": "hub"}, ts=1001, index_conn=index_conn)
    # Second reference must not double-count the before-metric.
    record_event(sessions_conn, session.id, tool="get_neuron",
                 args={"name": "hub"}, ts=1002, index_conn=index_conn)
    record_event(sessions_conn, session.id, tool="cerebrofy_impact",
                 args={"target": "caller"}, ts=1003, index_conn=index_conn)

    session = get_session(sessions_conn, session.id)
    assert session is not None
    assert session.neurons_touched == ("a.py::hub", "a.py::caller")
    assert session.blast_radius_before == 4  # hub (3 callers) + caller (1)


def test_record_event_without_index_conn_skips_metrics(
    sessions_conn: sqlite3.Connection,
) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    record_event(sessions_conn, session.id, tool="cerebrofy_impact",
                 args={"target": "hub"}, ts=1001)
    session = get_session(sessions_conn, session.id)
    assert session is not None
    assert session.neurons_touched == ()
    assert session.blast_radius_before is None


def test_tracking_is_capped_at_max_tracked_neurons(
    tmp_path: Path, sessions_conn: sqlite3.Connection
) -> None:
    # The tracked-neuron cap is an implementation constant (50); the test
    # asserts the *capping behaviour* against a literal rather than importing
    # the private ``MAX_TRACKED_NEURONS`` constant.
    cap = 50
    cerebrofy_dir = _cerebrofy_dir(tmp_path / "index")
    index_conn = sqlite3.connect(cerebrofy_dir / "db" / "cerebrofy.db")
    create_schema(index_conn, embed_dim=0)
    for i in range(cap + 10):
        index_conn.execute(
            "INSERT INTO nodes VALUES (?,?,'many.py','function',1,1,NULL,NULL,NULL)",
            (f"many.py::fn{i}", f"fn{i}"),
        )
    index_conn.commit()

    session = start_session(sessions_conn, task="T", now=1000)
    for i in range(cap + 10):
        record_event(sessions_conn, session.id, tool="get_neuron",
                     args={"name": f"fn{i}"}, ts=1000 + i, index_conn=index_conn)
    session = get_session(sessions_conn, session.id)
    assert session is not None
    assert len(session.neurons_touched) == cap
    assert len(session.neurons_touched) < cap + 10  # capped, not unbounded
    index_conn.close()


def test_end_session_recomputes_after_metric(
    sessions_conn: sqlite3.Connection, index_conn: sqlite3.Connection
) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    record_event(sessions_conn, session.id, tool="cerebrofy_impact",
                 args={"target": "hub"}, ts=1001, index_conn=index_conn)

    # Simulate the agent adding a new caller of hub before ending the session.
    index_conn.execute(
        "INSERT INTO nodes VALUES ('c.py::new','new','c.py','function',1,1,NULL,NULL,NULL)"
    )
    index_conn.execute("INSERT INTO edges VALUES ('c.py::new','a.py::hub','LOCAL_CALL','c.py')")
    index_conn.commit()

    session = end_session(sessions_conn, session.id, outcome="success", now=1100,
                          index_conn=index_conn)
    assert session.blast_radius_before == 3
    assert session.blast_radius_after == 4
    assert session.blast_radius_delta == 1


def test_end_session_after_metric_none_when_nothing_tracked(
    sessions_conn: sqlite3.Connection, index_conn: sqlite3.Connection
) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    session = end_session(sessions_conn, session.id, now=1001, index_conn=index_conn)
    assert session.blast_radius_after is None
    assert session.blast_radius_delta is None


def test_end_session_skips_neurons_missing_from_index(
    sessions_conn: sqlite3.Connection, index_conn: sqlite3.Connection
) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    record_event(sessions_conn, session.id, tool="cerebrofy_impact",
                 args={"target": "hub"}, ts=1001, index_conn=index_conn)
    index_conn.execute("DELETE FROM edges WHERE dst_id = 'a.py::hub'")
    index_conn.commit()
    session = end_session(sessions_conn, session.id, now=1002, index_conn=index_conn)
    assert session.blast_radius_before == 3
    assert session.blast_radius_after == 0


# ---------------------------------------------------------------------------
# Session search
# ---------------------------------------------------------------------------

def test_search_sessions_task_text_fallback(sessions_conn: sqlite3.Connection) -> None:
    start_session(sessions_conn, task="Add rate limiting", now=1000)
    start_session(sessions_conn, task="Refactor parser", now=2000)
    hits = search_sessions(sessions_conn, "rate")
    assert len(hits) == 1
    assert hits[0].match_kind == "task_text"
    assert "rate limiting" in hits[0].session.task
    assert search_sessions(sessions_conn, "zzz") == []
    assert search_sessions(sessions_conn, "  ") == []


def test_search_sessions_semantic_orders_by_similarity(
    sessions_conn: sqlite3.Connection,
) -> None:
    start_session(sessions_conn, task="alpha", now=1000,
                  embedding=[1.0] + [0.0] * 383)
    start_session(sessions_conn, task="beta", now=2000,
                  embedding=[0.0, 1.0] + [0.0] * 382)
    hits = search_sessions(sessions_conn, "alpha", query_embedding=[1.0] + [0.0] * 383,
                          limit=2)
    assert [h.session.task for h in hits] == ["alpha", "beta"]
    assert hits[0].score > hits[1].score
    assert hits[0].match_kind == "semantic"


def test_search_sessions_semantic_empty_when_no_vectors(
    sessions_conn: sqlite3.Connection,
) -> None:
    start_session(sessions_conn, task="alpha", now=1000)
    assert search_sessions(sessions_conn, "alpha", query_embedding=[1.0] + [0.0] * 383) == []


def test_start_session_with_embedding_stores_vector(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="alpha", now=1000,
                            embedding=[0.5] * 384)
    row = sessions_conn.execute(
        "SELECT COUNT(*) FROM vec_sessions WHERE rowid = "
        "(SELECT rowid FROM sessions WHERE id = ?)",
        (session.id,),
    ).fetchone()
    assert row is not None and row[0] == 1


# ---------------------------------------------------------------------------
# Row-decoding resilience
# ---------------------------------------------------------------------------

def test_corrupt_touched_json_decodes_to_empty(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    sessions_conn.execute(
        "UPDATE sessions SET neurons_touched = 'not-json' WHERE id = ?", (session.id,)
    )
    sessions_conn.commit()
    assert get_session(sessions_conn, session.id).neurons_touched == ()  # type: ignore[union-attr]


def test_corrupt_event_args_json_decodes_to_empty(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    sessions_conn.execute(
        "INSERT INTO session_events(session_id, ts, tool, args, result_summary) "
        "VALUES (?, 1, 'x', '{bad json', NULL)",
        (session.id,),
    )
    sessions_conn.commit()
    assert list_events(sessions_conn, session.id)[0].args == {}


def test_corrupt_session_json_logs_warning_and_does_not_crash(
    sessions_conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    """Corrupted session JSON must warn (module logger) and stay non-fatal."""
    import logging

    session = start_session(sessions_conn, task="T", now=1000)
    sessions_conn.execute(
        "INSERT INTO session_events(session_id, ts, tool, args, result_summary) "
        "VALUES (?, 1, 'x', '{bad', NULL)",
        (session.id,),
    )
    sessions_conn.commit()

    with caplog.at_level(logging.WARNING, logger="cerebrofy.session.recorder"):
        record = get_session(sessions_conn, session.id)
        events = list_events(sessions_conn, session.id)

    assert record is not None
    assert record.neurons_touched == ()
    assert events[0].args == {}
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("corrupt" in r.getMessage().lower() for r in warnings)


def test_json_args_survive_roundtrip(sessions_conn: sqlite3.Connection) -> None:
    session = start_session(sessions_conn, task="T", now=1000)
    args = {"query": "x", "n": 3, "flag": True, "nested": {"a": 1}}
    record_event(sessions_conn, session.id, tool="t", args=args, ts=1)
    stored = sessions_conn.execute(
        "SELECT args FROM session_events WHERE session_id = ?", (session.id,)
    ).fetchone()
    assert json.loads(stored[0]) == args


# ---------------------------------------------------------------------------
# #05 memory integration at session end (Phase 2 loop #11 -> #05 -> #11)
# ---------------------------------------------------------------------------


def test_write_session_summary_memory_writes_decision_memory(
    sessions_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    from unittest.mock import patch

    from cerebrofy.memory.store import list_memories, open_memories_db

    session = start_session(sessions_conn, task="Refactor parser", agent="claude", now=1000)
    closed = end_session(sessions_conn, session.id, outcome="success", notes="done", now=1060)

    with patch("cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384):
        wrote = write_session_summary_memory(_cerebrofy_dir(tmp_path), closed)
    assert wrote is True

    mconn = open_memories_db(_cerebrofy_dir(tmp_path))
    try:
        mems = list_memories(mconn, type_filter="decision")
    finally:
        mconn.close()
    assert len(mems) == 1
    mem = mems[0]
    assert mem.type == "decision"
    assert mem.title == "Refactor parser"
    assert "outcome=success" in mem.body
    assert "duration=60s" in mem.body
    assert mem.author == "agent:session-recorder"
    assert "session" in mem.tags
    assert "outcome:success" in mem.tags


def test_end_session_writes_summary_memory_on_close(
    sessions_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    from unittest.mock import patch

    from cerebrofy.memory.store import list_memories, open_memories_db

    session = start_session(sessions_conn, task="Add rate limiting", agent="bot", now=1000)
    with patch("cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384):
        updated = end_session(
            sessions_conn,
            session.id,
            outcome="success",
            notes="done",
            now=1060,
            cerebrofy_dir=_cerebrofy_dir(tmp_path),
        )
    assert updated.outcome == "success"
    assert not updated.is_active

    mconn = open_memories_db(_cerebrofy_dir(tmp_path))
    try:
        mems = list_memories(mconn, type_filter="decision")
    finally:
        mconn.close()
    assert len(mems) == 1
    assert mems[0].title == "Add rate limiting"


def test_end_session_skips_memory_without_cerebrofy_dir(
    sessions_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    from unittest.mock import patch

    session = start_session(sessions_conn, task="T", now=1000)
    with patch("cerebrofy.memory.store.open_memories_db") as open_mock, patch(
        "cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384
    ) as emb_mock, patch("cerebrofy.memory.store.write_memory") as write_mock:
        end_session(sessions_conn, session.id, outcome="success", now=1001)
    open_mock.assert_not_called()
    emb_mock.assert_not_called()
    write_mock.assert_not_called()


def test_end_session_memory_write_is_non_fatal(sessions_conn: sqlite3.Connection, tmp_path: Path) -> None:
    from unittest.mock import patch

    session = start_session(sessions_conn, task="T", now=1000)
    with patch(
        "cerebrofy.memory.store.open_memories_db",
        side_effect=RuntimeError("memories.db corrupt"),
    ):
        # Session must still close successfully even if the memory write fails.
        updated = end_session(
            sessions_conn,
            session.id,
            outcome="success",
            notes="n",
            now=1001,
            cerebrofy_dir=_cerebrofy_dir(tmp_path),
        )
    assert updated.outcome == "success"
    assert not updated.is_active


def test_write_session_summary_memory_swallows_store_failure(
    sessions_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    from unittest.mock import patch

    session = start_session(sessions_conn, task="T", now=1000)
    closed = end_session(sessions_conn, session.id, outcome="failed", now=1001)
    with patch("cerebrofy.memory.store.open_memories_db", side_effect=RuntimeError("db down")):
        assert write_session_summary_memory(_cerebrofy_dir(tmp_path), closed) is False


def test_write_session_summary_memory_swallows_embedder_failure(
    sessions_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    from unittest.mock import patch

    session = start_session(sessions_conn, task="T", now=1000)
    closed = end_session(sessions_conn, session.id, outcome="failed", now=1001)
    with patch("cerebrofy.memory.embedder.embed_memory", side_effect=RuntimeError("no model")):
        assert write_session_summary_memory(_cerebrofy_dir(tmp_path), closed) is False


# ---------------------------------------------------------------------------
# write_session_summary_memory split: pure builder + thin impure writer
# ---------------------------------------------------------------------------


def _closed_session() -> SessionRecord:
    return SessionRecord(
        id="sess_abc",
        task="Refactor parser",
        agent="claude",
        started_at=1000,
        ended_at=1060,
        outcome="success",
        outcome_notes="done",
        neurons_touched=("a.py::hub", "a.py::caller"),
        blast_radius_before=3,
        blast_radius_after=4,
        event_count=5,
    )


def test_build_session_memory_constructs_pure_memory() -> None:
    """Pure part: builds a #05 decision Memory with no IO / no mocks."""
    from unittest.mock import patch

    from cerebrofy.memory.store import Memory

    session = _closed_session()
    # No real embedder/db should be touched by the pure builder.
    with patch("cerebrofy.memory.store.open_memories_db") as db_mock, patch(
        "cerebrofy.memory.embedder.embed_memory"
    ) as emb_mock:
        mem = build_session_memory(session)

    db_mock.assert_not_called()
    emb_mock.assert_not_called()
    assert isinstance(mem, Memory)
    assert mem.type == "decision"
    assert mem.title == "Refactor parser"
    assert mem.author == "agent:session-recorder"
    assert mem.neuron_id is None and mem.lobe is None
    assert mem.decay_score == 1.0
    assert mem.status == "active"
    assert mem.created_ts == 1060  # derived from ended_at, not time.time()
    assert "session" in mem.tags
    assert "outcome:success" in mem.tags
    assert "agent=claude" in mem.body
    assert "outcome=success" in mem.body
    assert "duration=60s" in mem.body
    assert "events=5" in mem.body
    assert "neurons_touched=2" in mem.body
    assert "blast_radius_before=3 -> after=4" in mem.body
    assert "notes: done" in mem.body


def test_build_session_memory_omits_blast_and_notes_when_unset() -> None:
    session = SessionRecord(
        id="sess_x", task="T", agent=None, started_at=0, ended_at=10,
        outcome="unknown", outcome_notes=None, neurons_touched=(),
        blast_radius_before=None, blast_radius_after=None, event_count=0,
    )
    mem = build_session_memory(session)
    assert mem.title == "T"
    assert "blast_radius" not in mem.body
    assert "agent=unknown" in mem.body
    assert "outcome=unknown" in mem.body
    assert "notes:" not in mem.body
    assert "outcome:unknown" in mem.tags


def test_write_memory_if_possible_swallows_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Impure part: store failure is non-fatal and logged."""
    import logging
    from unittest.mock import patch

    from cerebrofy.memory.embedder import embed_memory

    mem = build_session_memory(_closed_session())
    with patch(
        "cerebrofy.memory.store.open_memories_db", side_effect=RuntimeError("db down")
    ):
        with caplog.at_level(logging.WARNING, logger="cerebrofy.session.recorder"):
            result = write_memory_if_possible(_cerebrofy_dir(tmp_path), mem, embed_memory)
    assert result is False
    assert "failed to write session summary memory" in caplog.text


# ---------------------------------------------------------------------------
# Migration 005 (sessions.sql) verification: fresh-create + idempotent upgrade
# ---------------------------------------------------------------------------


def test_migration_005_sessions_sql_creates_outcome_columns(tmp_path: Path) -> None:
    """migration/005_sessions.sql applies with outcome/outcome_notes from the start."""
    import sqlite_vec  # type: ignore[import-untyped]

    sql_path = Path(__file__).parents[2] / "migrations" / "005_sessions.sql"
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(sql_path.read_text(encoding="utf-8"))

    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert {"outcome", "outcome_notes", "blast_radius_before", "blast_radius_after",
            "event_count"} <= cols

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"sessions", "session_events", "vec_sessions"} <= tables

    # Upgrade path: re-applying the file must be idempotent (CREATE ... IF NOT EXISTS).
    conn.executescript(sql_path.read_text(encoding="utf-8"))
    conn.close()
