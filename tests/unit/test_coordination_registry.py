"""Unit tests for the persistent multi-agent registry (Idea #25)."""

from __future__ import annotations

import multiprocessing
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from cerebrofy.coordination.registry import ActiveAgentRegistry
from cerebrofy.db.schema import create_schema
from cerebrofy.errors import NEURON_ALREADY_CLAIMED, ClaimExpiredError, NoActiveAgentError


def _db_path(tmp_path: Path) -> Path:
    """Create a real (empty) index database and return its path."""
    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "cerebrofy.db"
    conn = sqlite3.connect(str(db_path))
    try:
        create_schema(conn, 0)
    finally:
        conn.close()
    return db_path


def _raw_update(db_path: Path, sql: str, params: tuple[object, ...]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _raw_row(db_path: Path, agent_id: str) -> tuple[object, ...] | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row: tuple[object, ...] | None = conn.execute(
            "SELECT agent_id, status, claimed_neurons, ttl_minutes, expires_ts "
            "FROM active_agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        return row
    finally:
        conn.close()


def test_claim_persists_across_registry_instances(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    first = ActiveAgentRegistry(db_path)
    try:
        result = first.claim_neurons(
            "agent-1",
            ["auth/tokens.py::validate_token"],
            "refactoring validate_token",
            agent_type="cursor",
        )
        assert result["claimed"] == ["auth/tokens.py::validate_token"]
        assert result["claim_id"].startswith("claim_")
    finally:
        first.close()

    second = ActiveAgentRegistry(db_path)
    try:
        agents = second.get_active_agents()
        assert "agent-1" in agents
        assert agents["agent-1"]["agent_type"] == "cursor"
        assert agents["agent-1"]["claimed_neurons"] == [
            "auth/tokens.py::validate_token"
        ]
        claims = second.get_claims()
        assert claims[0]["neuron"] == "auth/tokens.py::validate_token"
        assert claims[0]["intent"] == "refactoring validate_token"
    finally:
        second.close()


def test_requesting_agent_is_excluded_from_conflicts(tmp_path: Path) -> None:
    registry = ActiveAgentRegistry(_db_path(tmp_path))
    try:
        registry.claim_neurons("agent-1", ["neuron-a"], "work")
        own = registry.check_conflicts("agent-1", "neuron-a")
        other = registry.check_conflicts("agent-2", "neuron-a")

        assert own["conflict"] is False
        assert own["claiming_agents"] == []
        assert other["conflict"] is True
        assert [agent["agent_id"] for agent in other["claiming_agents"]] == ["agent-1"]
    finally:
        registry.close()


def test_conflicting_neuron_skipped_while_free_neuron_claimed(tmp_path: Path) -> None:
    registry = ActiveAgentRegistry(_db_path(tmp_path))
    try:
        registry.claim_neurons("agent-1", ["neuron-a"], "first")

        result = registry.claim_neurons("agent-2", ["neuron-a", "neuron-b"], "second")
        assert result["claimed"] == ["neuron-b"]
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["neuron"] == "neuron-a"
        assert result["conflicts"][0]["existing_claimant"] == "agent-1"
        assert "error" not in result

        # Claiming only the held neuron fails with the shared error code.
        blocked = registry.claim_neurons("agent-3", ["neuron-a"], "third")
        assert blocked["claimed"] == []
        assert blocked["error"] == NEURON_ALREADY_CLAIMED
    finally:
        registry.close()


def test_release_and_release_all(tmp_path: Path) -> None:
    registry = ActiveAgentRegistry(_db_path(tmp_path))
    try:
        registry.claim_neurons("agent-1", ["n1", "n2", "n3"], "work")

        partial = registry.release_neurons("agent-1", ["n1", "unknown"])
        assert partial["released"] == ["n1"]
        assert [claim["neuron"] for claim in registry.get_claims()] == ["n2", "n3"]

        remaining = registry.release_all("agent-1")
        assert remaining["released"] == ["n2", "n3"]
        assert registry.get_claims() == []

        with pytest.raises(NoActiveAgentError):
            registry.release_all("agent-1")
        with pytest.raises(NoActiveAgentError):
            registry.release_neurons("ghost", ["n1"])
    finally:
        registry.close()


def test_heartbeat_extends_expires_ts(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    registry = ActiveAgentRegistry(db_path)
    try:
        registry.claim_neurons("agent-1", ["n1"], "work", ttl_minutes=60)
        _raw_update(
            db_path,
            "UPDATE active_agents SET expires_ts = ? WHERE agent_id = ?",
            (int(time.time()) + 5, "agent-1"),
        )

        result = registry.heartbeat("agent-1")
        assert result["agent_id"] == "agent-1"
        assert result["status"] == "active"

        row = _raw_row(db_path, "agent-1")
        assert row is not None
        assert isinstance(row[4], int)
        expires_ts = row[4]
        assert expires_ts >= int(time.time()) + 59 * 60
    finally:
        registry.close()


def test_expired_claim_raises_and_cleanup_completes(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    registry = ActiveAgentRegistry(db_path)
    try:
        registry.claim_neurons("agent-1", ["n1"], "work", ttl_minutes=60)
        _raw_update(
            db_path,
            "UPDATE active_agents SET expires_ts = ? WHERE agent_id = ?",
            (int(time.time()) - 10, "agent-1"),
        )

        with pytest.raises(ClaimExpiredError):
            registry.heartbeat("agent-1")
        with pytest.raises(ClaimExpiredError):
            registry.release_all("agent-1")

        cleaned = registry.cleanup_stale_agents()
        assert [agent["agent_id"] for agent in cleaned] == ["agent-1"]
        assert cleaned[0]["status"] == "completed"
        assert cleaned[0]["claimed_neurons"] == []

        row = _raw_row(db_path, "agent-1")
        assert row is not None
        assert row[1] == "completed"
        assert row[2] == "[]"
        assert registry.get_active_agents() == {}
    finally:
        registry.close()


def test_detect_overlapping_claims(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    registry = ActiveAgentRegistry(db_path)
    try:
        registry.claim_neurons("agent-1", ["n1"], "work")
        registry.claim_neurons("agent-2", ["n2"], "other work")
        # Simulate a race/legacy state where both rows hold n1.
        _raw_update(
            db_path,
            "UPDATE active_agents SET claimed_neurons = ? WHERE agent_id = ?",
            ('["n1", "n2"]', "agent-2"),
        )

        overlapping = registry.detect_overlapping_claims()
        assert overlapping == [{"neuron": "n1", "agents": ["agent-1", "agent-2"]}]
    finally:
        registry.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    registry = ActiveAgentRegistry(_db_path(tmp_path))
    registry.close()
    registry.close()


def test_missing_db_raises_without_creating_anything(tmp_path: Path) -> None:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"

    with pytest.raises(FileNotFoundError, match="Index not found"):
        ActiveAgentRegistry(db_path)

    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_existing_current_schema_issues_no_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cerebrofy.coordination.registry as registry_module

    db_path = _db_path(tmp_path)

    def _unexpected_write(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("write_transaction must not run for an up-to-date schema")

    monkeypatch.setattr(registry_module, "write_transaction", _unexpected_write)
    registry = ActiveAgentRegistry(db_path)
    try:
        assert registry.conn.execute("SELECT COUNT(*) FROM active_agents").fetchone() == (
            0,
        )
    finally:
        registry.close()


def test_legacy_schema_is_upgraded_in_place(tmp_path: Path) -> None:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.parent.mkdir(parents=True)
    legacy_conn = sqlite3.connect(str(db_path))
    try:
        legacy_conn.executescript(
            """
            CREATE TABLE active_agents (
              agent_id        TEXT PRIMARY KEY,
              agent_type      TEXT NOT NULL,
              session_id      TEXT,
              intent          TEXT,
              claimed_neurons TEXT NOT NULL DEFAULT '[]',
              started_ts      INTEGER NOT NULL,
              last_heartbeat  INTEGER NOT NULL,
              status          TEXT DEFAULT 'active'
            );
            """
        )
        legacy_conn.execute(
            "INSERT INTO active_agents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-agent",
                "cursor",
                "sess-1",
                "old work",
                '["n1"]',
                1_000,
                1_000,
                "active",
            ),
        )
        legacy_conn.commit()
    finally:
        legacy_conn.close()

    registry = ActiveAgentRegistry(db_path)
    try:
        columns = {
            str(row[1])
            for row in registry.conn.execute(
                "PRAGMA table_info(active_agents)"
            ).fetchall()
        }
        assert {"ttl_minutes", "expires_ts", "created_ts"} <= columns

        row = registry.conn.execute(
            "SELECT ttl_minutes, created_ts FROM active_agents "
            "WHERE agent_id = 'legacy-agent'"
        ).fetchone()
        assert row is not None
        assert row[0] == 60
        assert row[1] == 1_000
    finally:
        registry.close()


def test_heartbeat_staleness_cleans_future_expiry(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    registry = ActiveAgentRegistry(db_path, heartbeat_interval=10)
    try:
        registry.claim_neurons("agent-1", ["n1"], "work", ttl_minutes=60)
        now = int(time.time())
        _raw_update(
            db_path,
            "UPDATE active_agents SET expires_ts = ?, last_heartbeat = ? "
            "WHERE agent_id = ?",
            (now + 3600, now - 25, "agent-1"),
        )

        cleaned = registry.cleanup_stale_agents()
        assert [agent["agent_id"] for agent in cleaned] == ["agent-1"]
        assert registry.get_active_agents(cleanup=False) == {}
    finally:
        registry.close()


def test_release_after_sweep_raises_claim_expired(tmp_path: Path) -> None:
    db_path = _db_path(tmp_path)
    registry = ActiveAgentRegistry(db_path)
    try:
        registry.claim_neurons("agent-1", ["n1"], "work", ttl_minutes=60)
        _raw_update(
            db_path,
            "UPDATE active_agents SET expires_ts = ? WHERE agent_id = ?",
            (int(time.time()) - 10, "agent-1"),
        )

        # ``who`` sweeps stale claims and marks the agent completed.
        assert registry.get_active_agents() == {}

        with pytest.raises(ClaimExpiredError):
            registry.release_neurons("agent-1", ["n1"])
        with pytest.raises(ClaimExpiredError):
            registry.release_all("agent-1")
        with pytest.raises(ClaimExpiredError):
            registry.heartbeat("agent-1")
    finally:
        registry.close()


def test_agent_type_only_overridden_when_explicit(tmp_path: Path) -> None:
    registry = ActiveAgentRegistry(_db_path(tmp_path))
    try:
        registry.claim_neurons("agent-1", ["n1"], "work", agent_type="cursor")
        registry.claim_neurons("agent-1", ["n2"], "more work")
        assert registry.get_active_agents()["agent-1"]["agent_type"] == "cursor"

        registry.claim_neurons("agent-1", ["n3"], "more work", agent_type="human")
        assert registry.get_active_agents()["agent-1"]["agent_type"] == "human"

        registry.claim_neurons("agent-2", ["n4"], "new agent")
        assert registry.get_active_agents()["agent-2"]["agent_type"] == "claude"
    finally:
        registry.close()


def test_claim_id_is_deterministic(tmp_path: Path) -> None:
    registry = ActiveAgentRegistry(_db_path(tmp_path))
    try:
        first = registry.claim_neurons("agent-1", ["n2", "n1"], "work", ttl_minutes=60)
        second = registry.claim_neurons("agent-1", ["n1", "n2"], "work", ttl_minutes=60)

        assert first["claim_id"].startswith("claim_")
        assert first["claim_id"] == second["claim_id"]

        other = registry.claim_neurons("agent-2", ["n3"], "work", ttl_minutes=60)
        assert other["claim_id"] != first["claim_id"]
    finally:
        registry.close()


def test_readonly_opens_do_not_create_or_modify(tmp_path: Path) -> None:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    try:
        from cerebrofy.db.schema import ACTIVE_AGENTS_DDL

        conn.executescript(ACTIVE_AGENTS_DDL)
        conn.execute(
            "INSERT INTO active_agents (agent_id, agent_type, claimed_neurons, "
            "started_ts, last_heartbeat, status, ttl_minutes, expires_ts) "
            "VALUES ('agent-1', 'claude', '[\"n1\"]', 1000, 1000, 'active', 60, 9999999999)"
        )
        conn.commit()
    finally:
        conn.close()

    before = {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }

    registry = ActiveAgentRegistry(db_path, readonly=True)
    try:
        assert registry.readonly is True
        assert set(registry.get_active_agents()) == {"agent-1"}
        assert registry.check_conflicts("agent-2", "n1")["conflict"] is True
        assert registry.detect_overlapping_claims() == []
    finally:
        registry.close()

    after = {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    assert after == before


def test_readonly_missing_db_raises_without_creating(tmp_path: Path) -> None:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    with pytest.raises(FileNotFoundError, match="Index not found"):
        ActiveAgentRegistry(db_path, readonly=True)
    assert not db_path.parent.exists()


def _claim_in_process(args: tuple[str, str]) -> dict[str, Any]:
    db_path, agent_id = args
    registry = ActiveAgentRegistry(db_path)
    try:
        return registry.claim_neurons(agent_id, ["contended/neuron"], "race")
    finally:
        registry.close()


@pytest.mark.parametrize("processes", [2, 4, 6])
def test_concurrent_claims_have_exactly_one_winner(
    tmp_path: Path, processes: int
) -> None:
    db_path = _db_path(tmp_path)
    jobs = [(str(db_path), f"agent-{index}") for index in range(processes)]

    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=processes, mp_context=context) as pool:
        results = list(pool.map(_claim_in_process, jobs))

    winners = [
        result for result in results if result["claimed"] == ["contended/neuron"]
    ]
    assert len(winners) == 1, results
    for result in results:
        if result is winners[0]:
            continue
        assert result["claimed"] == []
        assert result["conflicts"][0]["neuron"] == "contended/neuron"

    registry = ActiveAgentRegistry(db_path)
    try:
        claims = registry.get_claims()
        assert [claim["neuron"] for claim in claims] == ["contended/neuron"]
    finally:
        registry.close()
