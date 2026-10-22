"""Schema parity tests for multi-agent coordination (Idea #25)."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from cerebrofy.db.schema import ACTIVE_AGENTS_DDL, create_schema

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "007_coordination.sql"
)


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _table_body(sql: str) -> str:
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS active_agents\s*\((.*?)\);",
        _strip_sql_comments(sql),
        re.DOTALL,
    )
    assert match is not None, "active_agents CREATE TABLE not found"
    return _normalise(match.group(1))


def _index_names(sql: str) -> set[str]:
    return set(
        re.findall(
            r"CREATE INDEX IF NOT EXISTS\s+(\w+)",
            _strip_sql_comments(sql),
            re.IGNORECASE,
        )
    )


def test_active_agents_ddl_matches_migration() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert _table_body(ACTIVE_AGENTS_DDL) == _table_body(migration)
    assert _index_names(ACTIVE_AGENTS_DDL) == _index_names(migration)


def test_created_ts_default_is_sqlite_pre_3_38_compatible() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "unixepoch()" not in ACTIVE_AGENTS_DDL
    assert "unixepoch()" not in migration
    assert "DEFAULT (strftime('%s','now'))" in ACTIVE_AGENTS_DDL
    assert "DEFAULT (strftime('%s','now'))" in migration


def test_no_index_on_claimed_neurons() -> None:
    migration = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "idx_active_agents_neuron" not in ACTIVE_AGENTS_DDL
    assert "idx_active_agents_neuron" not in migration


def test_fresh_schema_backfills_created_ts_by_default() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        create_schema(conn, 0)
        before = int(time.time())
        conn.execute(
            "INSERT INTO active_agents (agent_id, agent_type, claimed_neurons, "
            "started_ts, last_heartbeat) VALUES ('agent-1', 'claude', '[]', 1, 1)"
        )
        row = conn.execute(
            "SELECT created_ts FROM active_agents WHERE agent_id = 'agent-1'"
        ).fetchone()
        assert row is not None
        assert isinstance(row[0], int)
        assert before <= row[0] <= int(time.time()) + 1
    finally:
        conn.close()
