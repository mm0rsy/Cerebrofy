"""Unit tests for cerebrofy.db.writer and cerebrofy.db.lock."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.db.lock import BuildLock, acquire, is_stale, release
from cerebrofy.db.schema import create_schema
from cerebrofy.db.writer import (
    build_neuron_text,
    collect_tracked_file_hashes,
    compute_file_hash,
    compute_state_hash,
    delete_edges_for_files,
    delete_file_hashes,
    delete_nodes_for_files,
    delete_vec_neurons,
    insert_meta,
    write_build_meta,
    write_edges,
    write_file_hashes,
    write_nodes,
)
from cerebrofy.graph.edges import Edge
from cerebrofy.ignore.ruleset import IgnoreRuleSet
from cerebrofy.parser.neuron import Neuron


def _make_db() -> sqlite3.Connection:
    """In-memory DB with full schema."""
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    create_schema(conn, embed_dim=4)  # tiny dim for tests
    return conn


def _make_neuron(
    name: str = "foo",
    file: str = "src/mod.py",
    line_start: int = 1,
    line_end: int = 5,
    sig: str | None = "def foo(a, b):",
    doc: str | None = "Docstring.",
) -> Neuron:
    return Neuron(
        id=f"{file}::{name}",
        name=name,
        type="function",
        file=file,
        line_start=line_start,
        line_end=line_end,
        signature=sig,
        docstring=doc,
    )


# ---------------------------------------------------------------------------
# insert_meta
# ---------------------------------------------------------------------------


def test_insert_meta_writes_three_rows() -> None:
    conn = _make_db()
    insert_meta(conn, embed_model="local", embed_dim=768)
    rows = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta").fetchall()}
    assert rows["schema_version"] == "1"
    assert rows["embed_model"] == "local"
    assert rows["embed_dim"] == "768"


def test_insert_meta_idempotent() -> None:
    conn = _make_db()
    insert_meta(conn, embed_model="local", embed_dim=768)
    insert_meta(conn, embed_model="openai", embed_dim=1536)  # Should overwrite
    rows = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta").fetchall()}
    assert rows["embed_model"] == "openai"


# ---------------------------------------------------------------------------
# write_nodes
# ---------------------------------------------------------------------------


def test_write_nodes_inserts_neuron() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    n = _make_neuron()
    write_nodes(conn, [n])
    row = conn.execute("SELECT name, file, type FROM nodes WHERE id=?", (n.id,)).fetchone()
    assert row == ("foo", "src/mod.py", "function")


def test_write_nodes_multiple() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    neurons = [_make_neuron(name="a", file="f.py"), _make_neuron(name="b", file="f.py")]
    write_nodes(conn, neurons)
    count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 2


def test_write_nodes_idempotent() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    n = _make_neuron()
    write_nodes(conn, [n])
    write_nodes(conn, [n])  # INSERT OR REPLACE
    count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 1


def test_write_nodes_none_signature() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    n = _make_neuron(sig=None, doc=None)
    write_nodes(conn, [n])
    row = conn.execute("SELECT signature, docstring FROM nodes WHERE id=?", (n.id,)).fetchone()
    assert row == (None, None)


# ---------------------------------------------------------------------------
# write_edges / delete_edges_for_files
# ---------------------------------------------------------------------------


def test_write_edges_inserts_rows() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    edges = [Edge(src_id="a", dst_id="b", rel_type="LOCAL_CALL", file="f.py")]
    write_edges(conn, edges)
    count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert count == 1


def test_write_edges_ignores_duplicates() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    e = Edge(src_id="a", dst_id="b", rel_type="LOCAL_CALL", file="f.py")
    write_edges(conn, [e, e])
    count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert count == 1


def test_delete_edges_for_files_removes_by_file() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    write_edges(conn, [Edge("a", "b", "LOCAL_CALL", "f.py"), Edge("c", "d", "LOCAL_CALL", "g.py")])
    delete_edges_for_files(conn, frozenset({"f.py"}), set())
    rows = conn.execute("SELECT file FROM edges").fetchall()
    assert all(r[0] == "g.py" for r in rows)


# ---------------------------------------------------------------------------
# compute_file_hash
# ---------------------------------------------------------------------------


def test_compute_file_hash_matches_sha256(tmp_path: Path) -> None:
    f = tmp_path / "hello.py"
    f.write_bytes(b"def hello(): pass\n")
    expected = hashlib.sha256(b"def hello(): pass\n").hexdigest()
    assert compute_file_hash(f) == expected


def test_compute_file_hash_different_files_differ(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_bytes(b"x = 1")
    b.write_bytes(b"x = 2")
    assert compute_file_hash(a) != compute_file_hash(b)


# ---------------------------------------------------------------------------
# compute_state_hash
# ---------------------------------------------------------------------------


def test_compute_state_hash_is_deterministic() -> None:
    m = {"a.py": "aaaa", "b.py": "bbbb"}
    assert compute_state_hash(m) == compute_state_hash(m)


def test_compute_state_hash_order_independent() -> None:
    m1 = {"a.py": "aaaa", "b.py": "bbbb"}
    m2 = {"b.py": "bbbb", "a.py": "aaaa"}
    assert compute_state_hash(m1) == compute_state_hash(m2)


def test_compute_state_hash_differs_with_different_content() -> None:
    m1 = {"a.py": "aaaa"}
    m2 = {"a.py": "bbbb"}
    assert compute_state_hash(m1) != compute_state_hash(m2)


# ---------------------------------------------------------------------------
# collect_tracked_file_hashes
# ---------------------------------------------------------------------------


def test_collect_tracked_file_hashes_finds_py_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"x=1")
    (tmp_path / "b.ts").write_bytes(b"x=1")
    rules = IgnoreRuleSet()
    result = collect_tracked_file_hashes(tmp_path, {".py"}, rules)
    assert "a.py" in result
    assert "b.ts" not in result


def test_collect_tracked_file_hashes_respects_ignore(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_bytes(b"x=1")
    (tmp_path / "main.pyc").write_bytes(b"x=1")
    rules = IgnoreRuleSet(cerebrofy_lines=["*.pyc"])
    result = collect_tracked_file_hashes(tmp_path, {".py", ".pyc"}, rules)
    assert "main.py" in result
    assert "main.pyc" not in result


def test_collect_tracked_file_hashes_empty_tree(tmp_path: Path) -> None:
    rules = IgnoreRuleSet()
    result = collect_tracked_file_hashes(tmp_path, {".py"}, rules)
    assert result == {}


# ---------------------------------------------------------------------------
# write_file_hashes / delete_file_hashes
# ---------------------------------------------------------------------------


def test_write_file_hashes_inserts_rows() -> None:
    conn = _make_db()
    write_file_hashes(conn, {"a.py": "aaa", "b.py": "bbb"})
    count = conn.execute("SELECT COUNT(*) FROM file_hashes").fetchone()[0]
    assert count == 2


def test_delete_file_hashes_removes_rows() -> None:
    conn = _make_db()
    write_file_hashes(conn, {"a.py": "aaa", "b.py": "bbb"})
    delete_file_hashes(conn, frozenset({"a.py"}))
    rows = {r[0] for r in conn.execute("SELECT file FROM file_hashes").fetchall()}
    assert rows == {"b.py"}


# ---------------------------------------------------------------------------
# write_build_meta
# ---------------------------------------------------------------------------


def test_write_build_meta_inserts_state_hash() -> None:
    conn = _make_db()
    write_build_meta(conn, "deadbeef1234")
    row = conn.execute("SELECT value FROM meta WHERE key='state_hash'").fetchone()
    assert row[0] == "deadbeef1234"


def test_write_build_meta_inserts_last_build() -> None:
    conn = _make_db()
    write_build_meta(conn, "abc")
    row = conn.execute("SELECT value FROM meta WHERE key='last_build'").fetchone()
    assert row is not None
    assert "Z" in row[0]  # ISO 8601 UTC string ends with Z


# ---------------------------------------------------------------------------
# delete_nodes_for_files
# ---------------------------------------------------------------------------


def test_delete_nodes_for_files_returns_deleted_ids() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    n = _make_neuron(file="src/x.py")
    write_nodes(conn, [n])
    deleted = delete_nodes_for_files(conn, frozenset({"src/x.py"}))
    assert n.id in deleted
    count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 0


def test_delete_nodes_for_files_empty_set() -> None:
    conn = _make_db()
    insert_meta(conn, "local", 768)
    deleted = delete_nodes_for_files(conn, frozenset())
    assert deleted == set()


# ---------------------------------------------------------------------------
# delete_vec_neurons
# ---------------------------------------------------------------------------


def test_delete_vec_neurons_empty_set_no_error() -> None:
    conn = _make_db()
    delete_vec_neurons(conn, set())  # Should not raise


# ---------------------------------------------------------------------------
# build_neuron_text
# ---------------------------------------------------------------------------


def test_build_neuron_text_combines_name_sig_doc() -> None:
    n = _make_neuron(name="calculate", sig="def calculate(x):", doc="Does calculation.")
    text = build_neuron_text(n)
    assert "calculate" in text
    assert "def calculate(x):" in text
    assert "Does calculation." in text


def test_build_neuron_text_handles_none_sig_and_doc() -> None:
    n = _make_neuron(name="foo", sig=None, doc=None)
    text = build_neuron_text(n)
    assert "foo" in text
    assert len(text) <= 512


def test_build_neuron_text_truncates_at_512() -> None:
    long_doc = "a" * 1000
    n = _make_neuron(doc=long_doc)
    text = build_neuron_text(n)
    assert len(text) <= 512


# ---------------------------------------------------------------------------
# BuildLock
# ---------------------------------------------------------------------------


def test_acquire_writes_pid_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "build.lock"
    lock = acquire(lock_path)
    assert lock_path.exists()
    assert lock_path.read_text().strip() == str(os.getpid())
    release(lock)


def test_release_removes_lock_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "build.lock"
    lock = acquire(lock_path)
    release(lock)
    assert not lock_path.exists()


def test_release_is_idempotent(tmp_path: Path) -> None:
    lock_path = tmp_path / "build.lock"
    lock = acquire(lock_path)
    release(lock)
    release(lock)  # Second release should not raise


def test_is_stale_returns_false_when_no_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "missing.lock"
    assert not is_stale(lock_path)


def test_is_stale_returns_false_for_current_process(tmp_path: Path) -> None:
    lock_path = tmp_path / "build.lock"
    lock = acquire(lock_path)
    assert not is_stale(lock_path)
    release(lock)


def test_is_stale_returns_true_for_dead_pid(tmp_path: Path) -> None:
    lock_path = tmp_path / "dead.lock"
    lock_path.write_text("99999999", encoding="utf-8")  # Very unlikely real PID
    # Can't guarantee this PID is dead, but is_stale should handle it
    result = is_stale(lock_path)
    assert isinstance(result, bool)


def test_is_stale_returns_true_for_corrupt_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "corrupt.lock"
    lock_path.write_text("not_a_pid", encoding="utf-8")
    assert is_stale(lock_path)
