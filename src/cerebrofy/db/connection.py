"""Database connection helpers for cerebrofy.db."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec  # type: ignore[import-untyped]

# Process-wide lock that serializes all in-process multi-statement writers on
# a single ``cerebrofy.db`` connection. Reads stay lock-free; only writers block
# on this lock. An ``RLock`` is used so a thread that already holds the lock is
# not itself blocked by re-entry — but re-entry on the *same connection* is still
# rejected below via the ``conn.in_transaction`` check (see ``write_transaction``).
_WRITE_LOCK = threading.RLock()


def open_db_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the index in read-only mode (safe alongside builders and MCP servers).

    Loads the sqlite-vec extension so vector search operations work correctly.
    """
    if not db_path.exists():
        raise FileNotFoundError("Index not found. Run 'cerebrofy build' first.")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open cerebrofy.db, load the sqlite-vec extension, and enable WAL mode.

    Does NOT perform a schema version check — that is the caller's responsibility.
    """
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def check_schema_version(conn: sqlite3.Connection, expected: int = 1) -> None:
    """Assert the schema version matches expected, or raise ValueError.

    Must be called before any read or write on an existing cerebrofy.db.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None or int(row[0]) != expected:
        got = row[0] if row is not None else None
        raise ValueError(f"Schema version mismatch: expected {expected}, got {got}")


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serialize and atomically commit a multi-statement DB write.

    This is the **required** entry point for any multi-statement write that must
    be atomic — notably the partial-reindex DML in ``cerebrofy update`` (via
    ``_run_update_transaction``) and the build metadata / file-hash commit in
    ``cerebrofy build`` (via ``build_step5_commit``). Reads stay lock-free.

    Contract (in order):

    1. **Serialize**: acquire the process-wide ``_WRITE_LOCK`` (``threading.RLock``)
       so only one writer transaction runs at a time in-process. Concurrent
       writers on the *same* ``check_same_thread=False`` connection (e.g. the
       session middleware) therefore block here until the prior writer commits,
       rather than racing on the shared connection.
    2. **Reject nesting**: *after* obtaining the lock, if ``conn.in_transaction``
       is already ``True`` (a transaction is open on this connection — typically
       same-thread re-entry, since a different thread only reaches this check
       after the prior writer committed), raise
       ``RuntimeError("write_transaction cannot be nested")``. The check lives
       inside the lock so a nested call still fails fast (the owning thread
       re-acquires the reentrant lock instantly) while genuinely concurrent
       writers serialize instead of failing.
    3. **Begin**: issue ``BEGIN IMMEDIATE`` (acquires a SQLite reserved lock
       up-front) to avoid late ``database is locked`` errors.
       ``executescript`` is **not** used — atomic DDL lives in
       ``cerebrofy.db.schema`` which has its own single-transaction contract.
    4. **Commit / rollback**: on clean exit ``commit()``; on any exception from
       the ``with`` body ``rollback()`` then re-raise.
    5. **Release**: the ``_WRITE_LOCK`` is always released (the ``with`` block
       guarantees release even on exception).

    Note on threading: session middleware opens connections with
    ``check_same_thread=False`` so the same ``sqlite3.Connection`` can be shared
    across threads. Those connections must still obtain ``_WRITE_LOCK`` (via this
    helper) before writing; the ``sqlite3`` module's own per-connection mutex
    only serializes raw access, not application-level transaction boundaries.
    """
    with _WRITE_LOCK:
        if conn.in_transaction:
            raise RuntimeError("write_transaction cannot be nested")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
