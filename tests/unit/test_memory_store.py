"""Unit tests for memory/store.py."""
from __future__ import annotations

from pathlib import Path
import pytest
from cerebrofy.memory.store import open_memories_db


def test_open_memories_db_creates_tables(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "memories" in tables
    assert "memory_edges" in tables
    conn.close()


def test_open_memories_db_idempotent(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn1 = open_memories_db(cerebrofy_dir)
    conn1.close()
    conn2 = open_memories_db(cerebrofy_dir)
    conn2.close()
