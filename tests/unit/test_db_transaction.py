"""Unit tests for the DB write-transaction contract (write_transaction).

These tests cover the serialization/nesting/rollback behaviour of
``cerebrofy.db.connection.write_transaction`` and verify that the existing
callers (``_run_update_transaction``) still commit atomically and return the
same counts after the migration from manual ``BEGIN IMMEDIATE`` / ``COMMIT`` /
``rollback``.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.commands.build import build_step5_commit
from cerebrofy.commands.update import _run_update_transaction
from cerebrofy.config.loader import CerebrоfyConfig
from cerebrofy.db.connection import write_transaction
from cerebrofy.db.schema import create_schema
from cerebrofy.db.writer import (
    insert_meta,
    write_build_meta,
    write_edges,
    write_file_hashes,
    write_nodes,
)
from cerebrofy.graph.edges import Edge
from cerebrofy.ignore.ruleset import IgnoreRuleSet
from cerebrofy.parser.neuron import Neuron
from cerebrofy.update.scope_resolver import UpdateScope


def _make_db() -> sqlite3.Connection:
    """In-memory DB with full schema (mirrors test_db_schema helpers)."""
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
# write_transaction — pure unit behaviour
# ---------------------------------------------------------------------------


def test_write_transaction_commits_on_success(tmp_path: Path) -> None:
    """A clean body commits and releases the lock for the next writer."""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()  # leave in_transaction False before the first write_transaction

    with write_transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")

    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    # Lock was released: a second writer can enter.
    with write_transaction(conn):
        conn.execute("INSERT INTO t VALUES (2)")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    conn.close()


def test_write_transaction_rolls_back_on_exception(tmp_path: Path) -> None:
    """An exception in the body rolls back all writes and re-raises."""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()

    with pytest.raises(ValueError, match="boom"), write_transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise ValueError("boom")

    # Rolled back — no rows persisted.
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    # Lock released — another writer can enter.
    with write_transaction(conn):
        conn.execute("INSERT INTO t VALUES (99)")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    conn.close()


def test_write_transaction_rejects_nesting(tmp_path: Path) -> None:
    """A nested write_transaction on an already-in-transaction conn raises."""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()

    with write_transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(RuntimeError, match="cannot be nested"):
            with write_transaction(conn):  # same conn, already in a tx
                conn.execute("INSERT INTO t VALUES (2)")

    # Outer transaction still committed; inner never wrote.
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    conn.close()


def test_write_transaction_serializes_threads(tmp_path: Path) -> None:
    """Two threads share one connection: the second cannot enter until the first exits.

    Uses a shared ``check_same_thread=False`` file connection (mirroring session
    middleware) plus Events + short timeouts — no long sleeps.
    """
    conn = sqlite3.connect(str(tmp_path / "ser.db"), check_same_thread=False)
    conn.execute("CREATE TABLE counter (n INTEGER)")
    conn.commit()

    t1_in = threading.Event()
    t2_in = threading.Event()
    allow_t1_exit = threading.Event()
    t1_done = threading.Event()

    def t1() -> None:
        with write_transaction(conn):
            t1_in.set()
            conn.execute("INSERT INTO counter VALUES (1)")
            # Hold the lock + transaction open so t2 must wait.
            allow_t1_exit.wait(timeout=2.0)
        t1_done.set()

    def t2() -> None:
        # Wait until t1 is confirmed inside the transaction holding the lock.
        assert t1_in.wait(timeout=2.0)
        with write_transaction(conn):
            t2_in.set()
            conn.execute("INSERT INTO counter VALUES (2)")

    th1 = threading.Thread(target=t1, name="writer-1")
    th2 = threading.Thread(target=t2, name="writer-2")
    th1.start()

    assert t1_in.wait(timeout=2.0), "t1 did not enter its transaction"
    th2.start()

    # Give t2 a window to attempt; it must be BLOCKED on the lock, not inside.
    assert not t2_in.wait(timeout=0.3), "t2 entered while t1 still holds the write lock"

    # Release t1 -> it commits and releases the lock -> t2 may now enter.
    allow_t1_exit.set()
    assert t1_done.wait(timeout=2.0), "t1 did not finish in time"
    assert t2_in.wait(timeout=2.0), "t2 did not enter after t1 released the lock"

    th2.join(timeout=2.0)

    n = conn.execute("SELECT COUNT(*) FROM counter").fetchone()[0]
    assert n == 2, f"both writes should persist, got {n}"
    conn.close()


# ---------------------------------------------------------------------------
# _run_update_transaction — migration sanity (count contract preserved)
# ---------------------------------------------------------------------------


def test_run_update_transaction_commits_and_returns_counts() -> None:
    """_run_update_transaction must commit atomically and return (reindexed, deleted).

    Scenario: a changed file is re-indexed. The seed neuron for that file is
    deleted (1 deleted) and a new neuron is inserted (1 reindexed). The returned
    tuple and the durable DB state after the call must both reflect the commit.
    """
    conn = _make_db()
    insert_meta(conn, embed_model="local", embed_dim=4)

    # Seed one neuron + edge + file hash for src/mod.py, then commit so the
    # connection is not left in a transaction (write_transaction rejects nesting).
    old_neuron = _make_neuron(name="old_foo", file="src/mod.py")
    write_nodes(conn, [old_neuron])
    write_edges(conn, [
        Edge(src_id=old_neuron.id, dst_id="dst", rel_type="LOCAL_CALL", file="src/mod.py"),
    ])
    write_file_hashes(conn, {"src/mod.py": "oldhash"})
    write_build_meta(conn, "oldstate")
    conn.commit()

    new_neuron = _make_neuron(name="new_foo", file="src/mod.py")
    scope = UpdateScope(
        changed_files=frozenset({"src/mod.py"}),
        deleted_files=frozenset(),
        affected_node_ids=frozenset({old_neuron.id}),
        affected_files=frozenset({"src/mod.py"}),
    )

    reindexed, deleted = _run_update_transaction(
        conn,
        scope=scope,
        new_neurons=[new_neuron],
        new_edges=[
            Edge(src_id=new_neuron.id, dst_id="dst", rel_type="LOCAL_CALL", file="src/mod.py"),
        ],
        file_hash_map={"src/mod.py": "newhash"},
        new_vectors={},  # no embedding for this unit test
        new_state_hash="newstate",
    )

    assert reindexed == 1
    assert deleted == 1

    # Durable after the implicit commit inside write_transaction.
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
    assert conn.execute("SELECT id FROM nodes").fetchone()[0] == new_neuron.id
    assert conn.execute("SELECT hash FROM file_hashes WHERE file='src/mod.py'").fetchone()[0] == "newhash"
    assert conn.execute("SELECT value FROM meta WHERE key='state_hash'").fetchone()[0] == "newstate"
    conn.close()


def test_run_update_transaction_rejected_when_already_in_transaction() -> None:
    """If the caller hands a connection mid-transaction, write_transaction raises.

    This guards the embedding-before-lock contract: update.py must not enter
    ``_run_update_transaction`` with an open transaction (which would hide
    writes or produce 'cannot start a transaction within a transaction').
    """
    conn = _make_db()
    insert_meta(conn, embed_model="local", embed_dim=4)

    old_neuron = _make_neuron(name="old_foo", file="src/mod.py")
    write_nodes(conn, [old_neuron])
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1

    scope = UpdateScope(
        changed_files=frozenset({"src/mod.py"}),
        deleted_files=frozenset(),
        affected_node_ids=frozenset({old_neuron.id}),
        affected_files=frozenset({"src/mod.py"}),
    )

    # Pre-open a transaction on the shared connection.
    conn.execute("BEGIN IMMEDIATE")  # conn.in_transaction is now True
    try:
        with pytest.raises(RuntimeError, match="cannot be nested"):
            _run_update_transaction(
                conn,
                scope=scope,
                new_neurons=[_make_neuron(name="new_foo", file="src/mod.py")],
                new_edges=[],
                file_hash_map={"src/mod.py": "newhash"},
                new_vectors={},
                new_state_hash="newstate",
            )
    finally:
        conn.rollback()  # clear the manually opened transaction

    # Seed neuron untouched (no commit ever happened inside the failed call).
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
    conn.close()


# ---------------------------------------------------------------------------
# build_step5_commit — flush pending build DML before write_transaction
# ---------------------------------------------------------------------------


def test_build_step5_commit_with_pending_transaction(tmp_path: Path) -> None:
    """build_step5_commit must flush accumulated build DML before the atomic commit.

    The build pipeline (step0 ``insert_meta`` plus ``write_nodes``/``write_edges``/
    ``upsert_vectors``) leaves a transaction open on the connection under Python's
    legacy sqlite3 auto-begin mode. ``build_step5_commit`` flushes that with an
    explicit ``conn.commit()`` before entering ``write_transaction`` so the
    nesting guard does not fire. Without that flush this raises
    ``RuntimeError("write_transaction cannot be nested")`` on every real build.
    """
    conn = _make_db()
    insert_meta(conn, embed_model="local", embed_dim=4)   # pending DML → in_tx True
    write_nodes(conn, [_make_neuron(name="keep_me", file="src/seed.py")])
    assert conn.in_transaction  # accumulated, not yet committed

    # A tracked source file under root so collect_tracked_file_hashes is non-empty.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def f():\n    pass\n", encoding="utf-8")

    config = CerebrоfyConfig(lobes={"pkg": str(pkg)}, tracked_extensions=[".py"])
    ignore = IgnoreRuleSet()

    state_hash = build_step5_commit(conn, tmp_path, config, ignore)

    # The seed neuron plus the file hash and state_hash meta are all durable.
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
    assert (
        conn.execute("SELECT hash FROM file_hashes WHERE file=?", ("pkg/mod.py",)).fetchone()[0]
        is not None
    )
    assert conn.execute("SELECT value FROM meta WHERE key='state_hash'").fetchone()[0] == state_hash
    # write_transaction left the connection clean.
    assert not conn.in_transaction
    conn.close()
