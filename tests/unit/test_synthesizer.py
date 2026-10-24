"""Unit tests for the Cross-Session Synthesizer (Idea #24)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cerebrofy.config.loader import build_default_config, load_config
from cerebrofy.db.schema import create_session_schema
from cerebrofy.memory.store import Memory, open_memories_db, write_memory
from cerebrofy.session._recorder.lifecycle import end_session, start_session
from cerebrofy.session._recorder.schema import open_sessions_db
from cerebrofy.synthesizer.analyzer import (
    Pattern,
    Session,
    _load_sessions,
    _parse_neurons_touched,
    closed_session_count,
    detect_agent_blind_spot,
    detect_effort_calibration,
    detect_failure_correlations,
    detect_lobe_fragility,
    detect_missing_step,
    list_synthesized_patterns,
    maybe_run_synthesis,
    parse_pattern_confidence,
    run_synthesis,
    sessions_until_next_synthesis,
    synthesize,
)


def _cerebrofy_dir(tmp_path: Path) -> Path:
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True, exist_ok=True)
    return cerebrofy_dir


def _session(
    session_id: str,
    outcome: str = "success",
    neurons: tuple[str, ...] = (),
    tools: tuple[str, ...] = (),
    *,
    task: str = "work",
    before: int = 0,
    after: int = 0,
) -> Session:
    return Session(
        id=session_id,
        started_at=1_000,
        ended_at=1_100,
        agent="agent",
        task=task,
        outcome=outcome,
        outcome_notes=None,
        neurons_touched=list(neurons),
        blast_radius_before=before,
        blast_radius_after=after,
        tool_sequence=list(tools),
    )


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    outcome: str = "success",
    neurons: tuple[str, ...] = (),
    tools: tuple[str, ...] = (),
    started_at: int = 1_000,
    task: str = "work",
    before: int = 0,
    after: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO sessions(id, started_at, ended_at, agent, task, outcome, "
        "outcome_notes, neurons_touched, blast_radius_before, blast_radius_after, "
        "event_count) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            session_id,
            started_at,
            started_at + 60,
            "agent",
            task,
            outcome,
            None,
            json.dumps(list(neurons)),
            before,
            after,
            len(tools),
        ),
    )
    for index, tool in enumerate(tools):
        conn.execute(
            "INSERT INTO session_events(session_id, ts, tool, args, result_summary) "
            "VALUES (?,?,?,?,?)",
            (session_id, started_at + index, tool, "{}", ""),
        )
    conn.commit()


def _seed_blind_spot(cerebrofy_dir: Path) -> None:
    """6 successful auth+tests sessions plus 5 auth-only failures."""
    conn = open_sessions_db(cerebrofy_dir)
    try:
        for index in range(6):
            _insert_session(
                conn,
                f"success_{index}",
                outcome="success",
                neurons=("auth/a.py", "tests/test_a.py"),
                tools=("search", "edit", "test"),
                started_at=1_000 + index,
            )
        for index in range(5):
            _insert_session(
                conn,
                f"failure_{index}",
                outcome="failed",
                neurons=("auth/b.py",),
                tools=("edit", "test"),
                started_at=2_000 + index,
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# B3 / m1: loading semantics
# ---------------------------------------------------------------------------


def test_parse_neurons_touched_uses_json_and_tolerates_corruption() -> None:
    assert _parse_neurons_touched('["auth/a.py", "db/b.py"]') == [
        "auth/a.py",
        "db/b.py",
    ]
    assert _parse_neurons_touched("{not json") == []
    assert _parse_neurons_touched('"auth/a.py"') == []
    assert _parse_neurons_touched(None) == []


def test_load_sessions_parses_json_neurons_touched(tmp_path: Path) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    conn = open_sessions_db(cerebrofy_dir)
    try:
        _insert_session(
            conn,
            "s1",
            neurons=("auth/a.py", "db/b.py"),
            tools=("impact", "edit"),
        )
        sessions = _load_sessions(conn)
    finally:
        conn.close()
    assert sessions[0].neurons_touched == ["auth/a.py", "db/b.py"]


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def test_detect_failure_correlations_keeps_perfect_predictors() -> None:
    sessions = [
        _session(
            f"fail_{index}",
            outcome="failed",
            neurons=("auth/a.py",),
            tools=("impact", "edit"),
        )
        for index in range(5)
    ] + [
        _session(
            f"ok_{index}",
            outcome="success",
            neurons=("db/b.py",),
            tools=("search", "edit"),
        )
        for index in range(5)
    ]

    patterns = detect_failure_correlations(sessions, 0.7)

    assert patterns, "0% failure rate without the sequence must not be discarded"
    match = next(p for p in patterns if "impact" in p.title)
    assert match.confidence == 1.0
    assert match.lobe == "auth"
    assert match.affected_lobes == ["auth"]


def test_detect_lobe_fragility_dedupes_sessions_per_lobe() -> None:
    sessions = [
        _session(
            f"s{index}",
            outcome="failed",
            neurons=("auth/a.py", "auth/b.py"),
        )
        for index in range(5)
    ]

    patterns = detect_lobe_fragility(sessions, 0.7)

    assert len(patterns) == 1
    assert patterns[0].type == "lobe_fragility"
    assert patterns[0].sample_size == 5  # not 10 (two neurons per session)
    assert patterns[0].lobe == "auth"


def test_detect_effort_calibration_requires_five_samples() -> None:
    four = [
        _session(f"u{index}", task="upgrade package", before=10, after=30)
        for index in range(4)
    ]
    assert detect_effort_calibration(four, 0.7) == []

    five = four + [_session("u4", task="upgrade package", before=10, after=30)]
    patterns = detect_effort_calibration(five, 0.7)

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.sample_size == 5
    assert "3.0×" in pattern.title
    assert "dynamic imports" not in pattern.title
    assert "dynamic imports" not in pattern.body
    assert "Measured" in pattern.body


def test_detect_missing_step_excludes_failure_correlations() -> None:
    sessions = [
        _session(f"ok{index}", tools=("read", "impact"))
        for index in range(5)
    ] + [
        _session(
            f"bad{index}", outcome="failed", tools=("deploy", "rollback")
        )
        for index in range(5)
    ]

    assert detect_missing_step(sessions, 0.7)  # candidate exists on success side
    assert detect_missing_step(
        sessions, 0.7, excluded={"read → impact"}
    ) == []


def test_detect_agent_blind_spot_names_missed_module() -> None:
    sessions = [
        _session(
            f"ok{index}", neurons=("auth/a.py", "tests/test_a.py")
        )
        for index in range(6)
    ] + [
        _session(f"bad{index}", outcome="failed", neurons=("auth/b.py",))
        for index in range(5)
    ]

    patterns = detect_agent_blind_spot(sessions, 0.7)

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.type == "agent_blind_spot"
    assert "tests" in pattern.title
    assert pattern.affected_lobes == ["auth", "tests"]
    assert pattern.lobe == "auth"
    assert pattern.sample_size == 5
    assert pattern.confidence == 1.0


def test_detect_agent_blind_spot_requires_five_samples() -> None:
    sessions = [
        _session(f"ok{index}", neurons=("auth/a.py", "tests/test_a.py"))
        for index in range(6)
    ] + [
        _session(f"bad{index}", outcome="failed", neurons=("auth/b.py",))
        for index in range(4)
    ]

    assert detect_agent_blind_spot(sessions, 0.7) == []


# ---------------------------------------------------------------------------
# M1 / B2 / M7 / M9: persistence and read-back
# ---------------------------------------------------------------------------


def test_run_synthesis_is_idempotent_and_preserves_created_ts(tmp_path: Path) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    _seed_blind_spot(cerebrofy_dir)

    first = run_synthesis(cerebrofy_dir)
    assert first
    first_result = synthesize(cerebrofy_dir)
    assert first_result.written == 0
    assert first_result.updated == 0

    mem_conn = open_memories_db(cerebrofy_dir)
    try:
        rows = mem_conn.execute(
            "SELECT id, title, created_ts FROM memories WHERE type = 'pattern'"
        ).fetchall()
        assert len(rows) == len(first)
        created = {row[0]: row[2] for row in rows}
    finally:
        mem_conn.close()

    second = run_synthesis(cerebrofy_dir)
    assert sorted(p.title for p in second) == sorted(p.title for p in first)

    mem_conn = open_memories_db(cerebrofy_dir)
    try:
        rows = mem_conn.execute(
            "SELECT id, created_ts FROM memories WHERE type = 'pattern'"
        ).fetchall()
    finally:
        mem_conn.close()
    assert len(rows) == len(first)
    assert {row[0]: row[1] for row in rows} == created


def test_run_synthesis_survives_memory_store_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    _seed_blind_spot(cerebrofy_dir)

    def _boom(_: Path) -> sqlite3.Connection:
        raise RuntimeError("memories.db unavailable")

    monkeypatch.setattr(
        "cerebrofy.synthesizer.analyzer.open_memories_db", _boom
    )

    patterns = run_synthesis(cerebrofy_dir)
    assert patterns, "computed patterns must survive a failed write"


def test_list_synthesized_patterns_parses_confidence_and_lobe(
    tmp_path: Path,
) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    _seed_blind_spot(cerebrofy_dir)
    patterns = run_synthesis(cerebrofy_dir)
    assert patterns

    conn = open_memories_db(cerebrofy_dir)
    try:
        stored = list_synthesized_patterns(conn)
        auth_patterns = list_synthesized_patterns(conn, lobe="auth")
        missing_lobe = list_synthesized_patterns(conn, lobe="does-not-exist")
    finally:
        conn.close()

    assert len(stored) == len(patterns)
    assert auth_patterns
    assert all(p.lobe == "auth" for p in auth_patterns)
    assert missing_lobe == []
    blind_spot = next(p for p in stored if p.type == "agent_blind_spot")
    assert blind_spot.confidence == 1.0
    assert blind_spot.sample_size == 5


def test_confidence_defaults_to_one_when_tag_absent(tmp_path: Path) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    conn = open_memories_db(cerebrofy_dir)
    try:
        write_memory(
            conn,
            Memory(
                id="legacy",
                neuron_id=None,
                lobe="auth",
                type="pattern",
                title="Legacy pattern",
                body="No confidence tag",
                author="cerebrofy-synthesizer",
                created_ts=1,
                tags=("synthesized", "lobe_fragility"),
                decay_score=1.0,
                status="active",
            ),
            [0.0] * 384,
        )
        conn.commit()
        patterns = list_synthesized_patterns(conn)
    finally:
        conn.close()

    assert len(patterns) == 1
    assert patterns[0].confidence == 1.0
    assert parse_pattern_confidence(()) == 1.0


# ---------------------------------------------------------------------------
# M4: automatic trigger
# ---------------------------------------------------------------------------


def test_maybe_run_synthesis_fires_only_on_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    conn = open_sessions_db(cerebrofy_dir)
    try:
        for index in range(9):
            _insert_session(conn, f"s{index}")
    finally:
        conn.close()

    calls: list[Path] = []

    def _fake_run(path: Path, **_: object) -> list[Pattern]:
        calls.append(path)
        return [Pattern("lobe_fragility", "t", "b", 1.0, 9, 9, ["auth"], 1)]

    monkeypatch.setattr(
        "cerebrofy.synthesizer.analyzer.run_synthesis", _fake_run
    )

    assert maybe_run_synthesis(cerebrofy_dir, every_n=10) == []
    assert calls == []

    conn = open_sessions_db(cerebrofy_dir)
    try:
        _insert_session(conn, "s9")
    finally:
        conn.close()

    assert maybe_run_synthesis(cerebrofy_dir, every_n=10)
    assert calls == [cerebrofy_dir]
    assert closed_session_count(cerebrofy_dir) == 10
    assert sessions_until_next_synthesis(cerebrofy_dir, 10) == 10


def test_maybe_run_synthesis_ignores_non_positive_interval(tmp_path: Path) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    conn = open_sessions_db(cerebrofy_dir)
    try:
        for index in range(10):
            _insert_session(conn, f"s{index}")
    finally:
        conn.close()

    assert maybe_run_synthesis(cerebrofy_dir, every_n=0) == []
    assert sessions_until_next_synthesis(cerebrofy_dir, 0) == 0


def test_session_end_synthesis_hook_is_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    conn = open_sessions_db(cerebrofy_dir)
    try:
        session = start_session(conn, task="work")
        monkeypatch.setattr(
            "cerebrofy.synthesizer.analyzer.maybe_run_synthesis",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        closed = end_session(
            conn,
            session.id,
            outcome="success",
            cerebrofy_dir=cerebrofy_dir,
            embed_memory_fn=lambda title, body: [0.0] * 384,
        )
    finally:
        conn.close()

    assert closed.outcome == "success"
    assert closed.ended_at is not None


def test_daemon_synthesis_trigger_is_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cerebrofy.insight.daemon import _trigger_synthesis

    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    monkeypatch.setattr(
        "cerebrofy.synthesizer.analyzer.maybe_run_synthesis",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _trigger_synthesis(cerebrofy_dir / "db" / "cerebrofy.db")


# ---------------------------------------------------------------------------
# M4 / M5: config + MCP surface
# ---------------------------------------------------------------------------


def _write_config(path: Path, synthesis: dict[str, int] | None = None) -> None:
    lines = ["lobes:", "  src: src/", "tracked_extensions:", "  - .py"]
    if synthesis is not None:
        lines.append("synthesis:")
        for key, value in synthesis.items():
            lines.append(f"  {key}: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_synthesis_config_default_and_override(tmp_path: Path) -> None:
    default_config = build_default_config({"src": "src/"})
    assert default_config["synthesis"] == {"every_n_sessions": 10}

    path = tmp_path / ".cerebrofy" / "config.yaml"
    _write_config(path)
    assert load_config(path).synthesis.every_n_sessions == 10

    _write_config(path, {"every_n_sessions": 3})
    assert load_config(path).synthesis.every_n_sessions == 3


def test_mcp_handler_read_and_run_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.synthesize import handle_synthesize

    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    _seed_blind_spot(cerebrofy_dir)
    monkeypatch.chdir(tmp_path)

    read_content = handle_synthesize({})
    payload = json.loads(read_content[0].text)
    assert payload["patterns_found"] == 0
    assert payload["patterns_written"] == 0
    assert payload["patterns"] == []
    assert payload["next_synthesis_at"] is None
    assert payload["sessions_until_next_synthesis"] == 9

    run_content = handle_synthesize({"run_now": True, "min_confidence": 0.0})
    run_payload = json.loads(run_content[0].text)
    assert run_payload["patterns_found"] >= 1
    assert run_payload["patterns_written"] >= 1
    assert run_payload["patterns"]
    assert run_payload["next_synthesis_at"] is None

    read_again = json.loads(handle_synthesize({})[0].text)
    assert read_again["patterns_found"] == run_payload["patterns_found"]
    assert read_again["patterns_written"] == 0


def test_server_attaches_patterns_for_lobe(tmp_path: Path) -> None:
    """M9: consumers get lobe-scoped patterns via the shared read helper."""
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _synthesized_patterns_for_lobes

    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    _seed_blind_spot(cerebrofy_dir)
    run_synthesis(cerebrofy_dir)

    auth_patterns = _synthesized_patterns_for_lobes(tmp_path, ["auth"])
    other_patterns = _synthesized_patterns_for_lobes(tmp_path, ["nope"])

    assert auth_patterns
    assert all(pattern["lobe"] == "auth" for pattern in auth_patterns)
    assert any(pattern["type"] == "agent_blind_spot" for pattern in auth_patterns)
    assert other_patterns == []


def test_create_session_schema_is_enough_for_synthesis(tmp_path: Path) -> None:
    """The runtime path uses create_session_schema directly (no recorder)."""
    cerebrofy_dir = _cerebrofy_dir(tmp_path)
    conn = sqlite3.connect(cerebrofy_dir / "db" / "sessions.db")
    from cerebrofy.db.vec import load_sqlite_vec

    load_sqlite_vec(conn)
    create_session_schema(conn)
    try:
        _insert_session(conn, "s1", tools=("impact", "edit"))
    finally:
        conn.close()

    assert closed_session_count(cerebrofy_dir) == 1
