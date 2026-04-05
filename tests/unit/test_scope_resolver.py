"""Unit tests for cerebrofy.update.scope_resolver._bfs_depth2."""

import sqlite3

import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.update.scope_resolver import _bfs_depth2


def _make_conn() -> sqlite3.Connection:
    """Create in-memory SQLite with edges schema for testing."""
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        "CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT NOT NULL, file TEXT)"
    )
    return conn


def test_bfs_depth1() -> None:
    conn = _make_conn()
    conn.execute("INSERT INTO edges VALUES ('A', 'B', 'LOCAL_CALL', 'f.py')")
    result = _bfs_depth2({"A"}, conn)
    assert "A" in result
    assert "B" in result


def test_bfs_depth2() -> None:
    conn = _make_conn()
    conn.execute("INSERT INTO edges VALUES ('A', 'B', 'LOCAL_CALL', 'f.py')")
    conn.execute("INSERT INTO edges VALUES ('B', 'C', 'LOCAL_CALL', 'f.py')")
    conn.execute("INSERT INTO edges VALUES ('C', 'D', 'LOCAL_CALL', 'f.py')")  # depth 3 — excluded
    result = _bfs_depth2({"A"}, conn)
    assert "A" in result
    assert "B" in result
    assert "C" in result
    assert "D" not in result  # Only 2 hops


def test_bfs_excludes_runtime_boundary() -> None:
    conn = _make_conn()
    conn.execute("INSERT INTO edges VALUES ('A', 'external::foo', 'RUNTIME_BOUNDARY', 'f.py')")
    conn.execute("INSERT INTO edges VALUES ('A', 'B', 'LOCAL_CALL', 'f.py')")
    result = _bfs_depth2({"A"}, conn)
    assert "external::foo" not in result
    assert "B" in result


def test_bfs_bidirectional() -> None:
    conn = _make_conn()
    conn.execute("INSERT INTO edges VALUES ('B', 'A', 'LOCAL_CALL', 'f.py')")  # inbound to A
    result = _bfs_depth2({"A"}, conn)
    assert "B" in result


def test_bfs_disconnected_nodes() -> None:
    conn = _make_conn()
    # No edges at all
    result = _bfs_depth2({"A"}, conn)
    assert result == {"A"}  # Seed node only


def test_bfs_empty_seeds() -> None:
    conn = _make_conn()
    result = _bfs_depth2(set(), conn)
    assert result == set()
