"""Unit tests for cerebrofy.update.scope_resolver (expanded)."""

from __future__ import annotations

import sqlite3

import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.update.change_detector import ChangeSet, FileChange
from cerebrofy.update.scope_resolver import (
    UpdateScope,
    _bfs_depth2,
    _get_files_for_node_ids,
    _get_node_ids_for_files,
    resolve_scope,
)


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, file TEXT, type TEXT, "
        "line_start INT, line_end INT, signature TEXT, docstring TEXT, hash TEXT)"
    )
    conn.execute(
        "CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT NOT NULL, file TEXT)"
    )
    return conn


# ---------------------------------------------------------------------------
# _get_node_ids_for_files
# ---------------------------------------------------------------------------


def test_get_node_ids_for_files_empty_set() -> None:
    conn = _make_conn()
    result = _get_node_ids_for_files(conn, frozenset())
    assert result == set()


def test_get_node_ids_for_files_returns_matching_ids() -> None:
    conn = _make_conn()
    conn.execute(
        "INSERT INTO nodes VALUES ('f.py::foo', 'foo', 'f.py', 'function', 1, 5, NULL, NULL, 'x')"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('g.py::bar', 'bar', 'g.py', 'function', 1, 5, NULL, NULL, 'y')"
    )
    result = _get_node_ids_for_files(conn, frozenset({"f.py"}))
    assert result == {"f.py::foo"}


# ---------------------------------------------------------------------------
# _get_files_for_node_ids
# ---------------------------------------------------------------------------


def test_get_files_for_node_ids_empty_set() -> None:
    conn = _make_conn()
    result = _get_files_for_node_ids(conn, set())
    assert result == set()


def test_get_files_for_node_ids_returns_distinct_files() -> None:
    conn = _make_conn()
    conn.execute("INSERT INTO nodes VALUES ('f.py::a', 'a', 'f.py', 'function', 1, 5, NULL, NULL, 'x')")
    conn.execute("INSERT INTO nodes VALUES ('f.py::b', 'b', 'f.py', 'function', 6, 10, NULL, NULL, 'y')")
    result = _get_files_for_node_ids(conn, {"f.py::a", "f.py::b"})
    assert result == {"f.py"}


# ---------------------------------------------------------------------------
# resolve_scope
# ---------------------------------------------------------------------------


def test_resolve_scope_changed_file_included() -> None:
    conn = _make_conn()
    conn.execute("INSERT INTO nodes VALUES ('f.py::foo', 'foo', 'f.py', 'function', 1, 5, NULL, NULL, 'x')")
    cs = ChangeSet(changes=(FileChange("f.py", "M"),), detected_via="git")
    scope = resolve_scope(cs, conn)
    assert "f.py" in scope.changed_files
    assert "f.py" in scope.affected_files


def test_resolve_scope_deleted_file_tracked() -> None:
    conn = _make_conn()
    conn.execute("INSERT INTO nodes VALUES ('f.py::foo', 'foo', 'f.py', 'function', 1, 5, NULL, NULL, 'x')")
    cs = ChangeSet(changes=(FileChange("f.py", "D"),), detected_via="git")
    scope = resolve_scope(cs, conn)
    assert "f.py" in scope.deleted_files


def test_resolve_scope_no_changes_empty_scope() -> None:
    conn = _make_conn()
    cs = ChangeSet(changes=(), detected_via="git")
    scope = resolve_scope(cs, conn)
    assert scope.changed_files == frozenset()
    assert scope.deleted_files == frozenset()
    assert scope.affected_node_ids == frozenset()


def test_resolve_scope_propagates_via_bfs() -> None:
    """Nodes connected to a changed file's nodes are included."""
    conn = _make_conn()
    conn.execute("INSERT INTO nodes VALUES ('f.py::foo', 'foo', 'f.py', 'function', 1, 5, NULL, NULL, 'x')")
    conn.execute("INSERT INTO nodes VALUES ('g.py::bar', 'bar', 'g.py', 'function', 1, 5, NULL, NULL, 'y')")
    conn.execute("INSERT INTO edges VALUES ('f.py::foo', 'g.py::bar', 'LOCAL_CALL', 'f.py')")
    cs = ChangeSet(changes=(FileChange("f.py", "M"),), detected_via="git")
    scope = resolve_scope(cs, conn)
    assert "g.py" in scope.affected_files


def test_resolve_scope_is_frozen_dataclass() -> None:
    import pytest
    conn = _make_conn()
    cs = ChangeSet(changes=(), detected_via="git")
    scope = resolve_scope(cs, conn)
    assert isinstance(scope, UpdateScope)
    with pytest.raises(Exception):
        scope.changed_files = frozenset()  # type: ignore[misc]
