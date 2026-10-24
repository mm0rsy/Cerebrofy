"""Schema parity tests for multi-agent coordination (Idea #25)."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from cerebrofy.db.schema import ACTIVE_AGENTS_DDL, create_schema


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


def test_active_agents_ddl_self_consistent() -> None:
    """ACTIVE_AGENTS_DDL should be self-consistent (no external migration file)."""
    # The DDL constant itself is the source of truth; ensure it has expected structure
    table_body = _table_body(ACTIVE_AGENTS_DDL)
    assert "agent_id" in table_body
    assert "agent_type" in table_body
    assert "claimed_neurons" in table_body
    assert "started_ts" in table_body
    assert "last_heartbeat" in table_body
    assert "created_ts" in table_body
    assert "PRIMARY KEY" in table_body

    index_names = _index_names(ACTIVE_AGENTS_DDL)
    assert "idx_active_agents_status" in index_names
    assert "idx_active_agents_heartbeat" in index_names


def test_created_ts_default_is_sqlite_pre_3_38_compatible() -> None:
    assert "unixepoch()" not in ACTIVE_AGENTS_DDL
    assert "DEFAULT (strftime('%s','now'))" in ACTIVE_AGENTS_DDL


def test_no_index_on_claimed_neurons() -> None:
    assert "idx_active_agents_neuron" not in ACTIVE_AGENTS_DDL


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