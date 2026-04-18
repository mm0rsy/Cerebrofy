"""Unit tests for cerebrofy.db.schema and cerebrofy.db.connection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.db.connection import check_schema_version, open_db
from cerebrofy.db.schema import (
    create_schema,
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
