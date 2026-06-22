"""Unit tests for memory/search.py."""
from __future__ import annotations

from pathlib import Path
from cerebrofy.memory.store import Memory, open_memories_db, write_memory
from cerebrofy.memory.search import recall_memories


def _make_conn(tmp_path: Path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    return open_memories_db(cerebrofy_dir)


def _mem(id: str, title: str = "T", body: str = "B", status: str = "active",
         lobe: str | None = None, type_: str = "warning") -> Memory:
    return Memory(
        id=id, neuron_id=None, lobe=lobe, type=type_,
        title=title, body=body, author="human:test",
        created_ts=1_000_000, tags=(), decay_score=1.0, status=status,
    )


def test_recall_returns_memories_by_similarity(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", title="JWT clock skew"), [1.0] + [0.0] * 383)
    write_memory(conn, _mem("m2", title="Database connection pool"), [0.0] + [1.0] + [0.0] * 382)
    conn.commit()
    results = recall_memories(conn, [1.0] + [0.0] * 383, limit=2)
    assert len(results) >= 1
    assert results[0][0].id == "m1"


def test_recall_excludes_stale_by_default(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", status="active"), [0.5] * 384)
    write_memory(conn, _mem("m2", status="stale"), [0.5] * 384)
    conn.commit()
    results = recall_memories(conn, [0.5] * 384, limit=10)
    ids = [r[0].id for r in results]
    assert "m1" in ids
    assert "m2" not in ids


def test_recall_includes_stale_when_flag_set(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", status="stale"), [0.5] * 384)
    conn.commit()
    results = recall_memories(conn, [0.5] * 384, limit=10, include_stale=True)
    assert any(r[0].id == "m1" for r in results)


def test_recall_filters_by_lobe(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", lobe="auth"), [0.5] * 384)
    write_memory(conn, _mem("m2", lobe="db"), [0.5] * 384)
    conn.commit()
    results = recall_memories(conn, [0.5] * 384, limit=10, lobe_filter="auth")
    ids = [r[0].id for r in results]
    assert "m1" in ids
    assert "m2" not in ids


def test_recall_returns_similarity_scores(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1"), [1.0] + [0.0] * 383)
    conn.commit()
    results = recall_memories(conn, [1.0] + [0.0] * 383, limit=5)
    assert len(results) == 1
    mem, score = results[0]
    assert 0.0 <= score <= 1.0
