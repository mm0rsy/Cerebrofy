"""Unit tests for cerebrofy.db.schema and cerebrofy.db.connection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.db import schema as schema_module
from cerebrofy.db.connection import check_schema_version, open_db
from cerebrofy.db.schema import (
    create_memory_schema,
    create_schema,
    create_session_schema,
)


def _make_vec_conn() -> sqlite3.Connection:
    """In-memory connection with sqlite_vec loaded."""
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


# ---------------------------------------------------------------------------
# create_schema
# ---------------------------------------------------------------------------


def test_create_schema_creates_nodes_table() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "nodes" in tables


def test_create_schema_creates_edges_table() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "edges" in tables


def test_create_schema_creates_meta_table() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "meta" in tables


def test_create_schema_creates_file_hashes_table() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "file_hashes" in tables


def test_create_schema_creates_vec_neurons_virtual_table() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "vec_neurons" in tables


def test_create_schema_nodes_columns() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
    assert {"id", "name", "file", "type", "line_start", "line_end", "signature", "docstring", "hash"}.issubset(cols)


def test_create_schema_edges_columns() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
    assert {"src_id", "dst_id", "rel_type", "file"}.issubset(cols)


def test_create_schema_accepts_custom_embed_dim() -> None:
    """vec_neurons table should be creatable with embed_dim=1536 without error."""
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=1536)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "vec_neurons" in tables


def test_create_schema_creates_file_index_on_nodes() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_nodes_file" in indexes


def test_create_schema_creates_indexes_on_edges() -> None:
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_edges_src" in indexes
    assert "idx_edges_dst" in indexes


# ---------------------------------------------------------------------------
# check_schema_version
# ---------------------------------------------------------------------------


def test_check_schema_version_passes_for_correct_version() -> None:
    conn = _make_vec_conn()
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    check_schema_version(conn, expected=1)  # Should not raise


def test_check_schema_version_raises_for_wrong_version() -> None:
    conn = _make_vec_conn()
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '99')")
    with pytest.raises(ValueError, match="Schema version mismatch"):
        check_schema_version(conn, expected=1)


def test_check_schema_version_raises_when_no_row() -> None:
    conn = _make_vec_conn()
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    with pytest.raises(ValueError):
        check_schema_version(conn, expected=1)


# ---------------------------------------------------------------------------
# open_db
# ---------------------------------------------------------------------------


def test_open_db_creates_and_opens_file(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    assert db_path.exists()
    # Should be a valid connection
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.close()


def test_open_db_enables_wal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "wal_test.db"
    conn = open_db(db_path)
    row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row[0] == "wal"
    conn.close()


# ---------------------------------------------------------------------------
# Transaction/commit contract (single transaction per schema creation)
# ---------------------------------------------------------------------------


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_create_schema_is_idempotent() -> None:
    """Repeated creation must be a no-op (CREATE ... IF NOT EXISTS)."""
    conn = _make_vec_conn()
    create_schema(conn, embed_dim=768)
    create_schema(conn, embed_dim=768)  # second call must not raise
    tables = _table_names(conn)
    assert {"nodes", "edges", "meta", "vec_neurons"} <= tables
    conn.close()


def test_create_session_schema_is_idempotent() -> None:
    conn = _make_vec_conn()
    create_session_schema(conn)
    create_session_schema(conn)
    tables = _table_names(conn)
    assert {"sessions", "session_events", "vec_sessions"} <= tables
    conn.close()


def test_create_memory_schema_is_idempotent() -> None:
    conn = _make_vec_conn()
    create_memory_schema(conn)
    create_memory_schema(conn)
    tables = _table_names(conn)
    assert {"memories", "memory_edges", "vec_memories"} <= tables
    conn.close()


def test_create_schema_rolls_back_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure mid-creation must not leave any tables behind (single tx).

    NARRATIVE_EVENTS_DDL is the last statement before ``vec_neurons``; patching it
    to broken SQL makes every earlier table get created in the active
    transaction, then fail — so the whole transaction must roll back.
    """
    conn = _make_vec_conn()
    monkeypatch.setattr(schema_module, "NARRATIVE_EVENTS_DDL", "CREATE TABLE narrative_events (broken")
    with pytest.raises(sqlite3.OperationalError):
        create_schema(conn, embed_dim=768)
    tables = _table_names(conn)
    assert "nodes" not in tables
    assert "edges" not in tables
    assert "meta" not in tables
    assert "vec_neurons" not in tables
    conn.close()


class _VecFailConn(sqlite3.Connection):
    """Connection subclass that fails when creating a specific vec0 table."""

    def execute(self, sql: str, *args: object, **kwargs: object) -> sqlite3.Cursor:
        if "vec_neurons" in str(sql):
            raise sqlite3.OperationalError("simulated vec0 failure")
        return super().execute(sql, *args, **kwargs)


def test_create_schema_vec_failure_rolls_back_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``vec_neurons`` creation failure must roll back even the DDL tables.

    vec0 virtual tables are created inline (not via ``_run_ddl``), so the fault
    is injected by routing the connection through a subclass factory before
    ``_make_vec_conn`` builds it. ``create_schema``'s single ``BEGIN IMMEDIATE``
    transaction must then roll everything — including ``vec_neurons`` — back.
    """
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: real_connect(
            *args, **{**kwargs, "factory": _VecFailConn}
        ),
    )
    conn = _make_vec_conn()
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated vec0 failure"):
            create_schema(conn, embed_dim=768)
        # create_schema raised and rolled back; inspect the still-live conn.
        tables = _table_names(conn)
        assert "nodes" not in tables
        assert "edges" not in tables
        assert "meta" not in tables
        assert "vec_neurons" not in tables
    finally:
        conn.close()


def test_create_session_schema_rolls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The session schema's vec step failing must roll back the regular tables."""
    conn = _make_vec_conn()
    real_run_ddl = schema_module._run_ddl

    def bomb(conn_: sqlite3.Connection, script: str) -> None:
        real_run_ddl(conn_, script)  # create tables inside the active tx
        raise sqlite3.OperationalError("simulated vec0 failure")

    monkeypatch.setattr(schema_module, "_run_ddl", bomb)
    with pytest.raises(sqlite3.OperationalError, match="vec0 failure"):
        create_session_schema(conn)
    tables = _table_names(conn)
    assert "sessions" not in tables
    assert "session_events" not in tables
    assert "vec_sessions" not in tables
    conn.close()
