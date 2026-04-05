"""Database connection helpers for cerebrofy.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec  # type: ignore[import-untyped]


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
