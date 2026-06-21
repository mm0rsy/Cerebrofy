"""Unit tests for memory/store.py."""
from __future__ import annotations

from pathlib import Path

from cerebrofy.memory.store import (
    Memory, MemoryEdge, open_memories_db,
    write_memory, get_memory, list_memories, delete_memory,
    write_memory_edge, trace_history,
)


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


def _make_conn(tmp_path: Path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    return open_memories_db(cerebrofy_dir)


def _mem(id: str = "m1", **kwargs) -> Memory:
    defaults = dict(
        neuron_id=None, lobe="auth", type="warning",
        title="Test memory", body="Body text",
        author="human:test@co.com", created_ts=1_000_000,
        tags=("security",), decay_score=1.0, status="active",
    )
    defaults.update(kwargs)
    return Memory(id=id, **defaults)


def test_write_and_get_memory(tmp_path):
    conn = _make_conn(tmp_path)
    m = _mem("abc", title="Clock skew", tags=("security", "jwt"))
    write_memory(conn, m, [0.1] * 384)
    conn.commit()
    result = get_memory(conn, "abc")
    assert result is not None
    assert result.title == "Clock skew"
    assert result.tags == ("security", "jwt")
    assert result.lobe == "auth"


def test_get_memory_missing_returns_none(tmp_path):
    conn = _make_conn(tmp_path)
    assert get_memory(conn, "nonexistent") is None


def test_list_memories_filter_lobe(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", lobe="auth"), [0.1] * 384)
    write_memory(conn, _mem("m2", lobe="db"), [0.1] * 384)
    conn.commit()
    results = list_memories(conn, lobe="auth")
    assert len(results) == 1
    assert results[0].id == "m1"


def test_list_memories_excludes_stale_by_default(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", status="active"), [0.1] * 384)
    write_memory(conn, _mem("m2", status="stale"), [0.1] * 384)
    conn.commit()
    assert len(list_memories(conn)) == 1
    assert len(list_memories(conn, include_stale=True)) == 2


def test_delete_memory(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1"), [0.1] * 384)
    conn.commit()
    delete_memory(conn, "m1")
    conn.commit()
    assert get_memory(conn, "m1") is None


def test_write_memory_edge_and_trace_history(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", title="Root"), [0.1] * 384)
    write_memory(conn, _mem("m2", title="Child"), [0.1] * 384)
    write_memory(conn, _mem("m3", title="Grandchild"), [0.1] * 384)
    conn.commit()
    write_memory_edge(conn, MemoryEdge("m1", "m2", "motivated", 1_000_000, None))
    write_memory_edge(conn, MemoryEdge("m2", "m3", "caused", 1_000_001, None))
    conn.commit()
    chain = trace_history(conn, "m3", depth=5)
    ids = [m.id for m in chain]
    assert "m3" in ids
    assert "m2" in ids
    assert "m1" in ids


def test_trace_history_depth_cap(tmp_path):
    conn = _make_conn(tmp_path)
    for i in range(10):
        write_memory(conn, _mem(f"m{i}"), [0.1] * 384)
    conn.commit()
    for i in range(9):
        write_memory_edge(conn, MemoryEdge(f"m{i}", f"m{i+1}", "caused", 1_000_000, None))
    conn.commit()
    chain = trace_history(conn, "m9", depth=3)
    assert len(chain) <= 3
