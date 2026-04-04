"""Unit tests for cerebrofy.search.hybrid."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.search.hybrid import (
    MatchedNeuron,
    _run_knn_query,
    _run_bfs,
    hybrid_search,
)
from cerebrofy.graph.edges import RUNTIME_BOUNDARY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_vec_db() -> sqlite3.Connection:
    """Open an in-memory DB with sqlite-vec loaded."""
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _seed_nodes(conn: sqlite3.Connection, nodes: list[tuple]) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS nodes "
        "(id TEXT PRIMARY KEY, name TEXT, file TEXT, type TEXT, "
        "line_start INT, line_end INT, signature TEXT, docstring TEXT, hash TEXT)"
    )
    for row in nodes:
        conn.execute("INSERT OR IGNORE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)


def _seed_edges(conn: sqlite3.Connection, edges: list[tuple]) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS edges "
        "(src_id TEXT, dst_id TEXT, rel_type TEXT NOT NULL, file TEXT, "
        "PRIMARY KEY (src_id, dst_id, rel_type))"
    )
    for row in edges:
        conn.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?)", row)


def _seed_meta(conn: sqlite3.Connection, embed_model: str = "local") -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES (?, ?)", ("embed_model", embed_model)
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES (?, ?)", ("schema_version", "1")
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES (?, ?)", ("state_hash", "abc123")
    )


# ---------------------------------------------------------------------------
# T037: _run_knn_query
# ---------------------------------------------------------------------------


def test_run_knn_query_returns_matched_neurons() -> None:
    """KNN results mapped to MatchedNeuron with correct similarity formula."""
    conn = _open_vec_db()
    _seed_nodes(conn, [
        ("file.py::foo", "foo", "file.py", "function", 1, 5, "def foo():", None, "h1"),
        ("file.py::bar", "bar", "file.py", "function", 10, 15, "def bar():", None, "h2"),
    ])
    conn.execute(
        "CREATE VIRTUAL TABLE vec_neurons USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[2])"
    )
    # Insert two vectors
    v1 = sqlite_vec.serialize_float32([1.0, 0.0])
    v2 = sqlite_vec.serialize_float32([0.0, 1.0])
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("file.py::foo", v1))
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("file.py::bar", v2))
    conn.commit()

    # Query with vector identical to foo → foo should be most similar
    query_vec = sqlite_vec.serialize_float32([1.0, 0.0])
    results = _run_knn_query(conn, query_vec, top_k=2)

    assert len(results) == 2
    assert results[0].name == "foo"
    assert results[0].similarity > results[1].similarity
    # similarity = 1 - distance/2; distance(identical) = 0 → similarity = 1.0
    assert results[0].similarity == pytest.approx(1.0, abs=0.01)


def test_run_knn_query_empty_db() -> None:
    """Empty vec_neurons table → returns empty list."""
    conn = _open_vec_db()
    _seed_nodes(conn, [])
    conn.execute(
        "CREATE VIRTUAL TABLE vec_neurons USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[2])"
    )
    conn.commit()

    query_vec = sqlite_vec.serialize_float32([1.0, 0.0])
    results = _run_knn_query(conn, query_vec, top_k=5)
    assert results == []


# ---------------------------------------------------------------------------
# T038: _run_bfs RUNTIME_BOUNDARY exclusion
# ---------------------------------------------------------------------------


def _make_bfs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    _seed_nodes(conn, [
        ("a", "a_func", "a.py", "function", 1, 5, None, None, "h"),
        ("b", "b_func", "b.py", "function", 1, 5, None, None, "h"),
        ("c", "c_func", "c.py", "function", 1, 5, None, None, "h"),
    ])
    _seed_edges(conn, [
        ("a", "b", "LOCAL_CALL", "a.py"),
        ("a", "c", RUNTIME_BOUNDARY, "a.py"),
    ])
    conn.commit()
    return conn


def test_bfs_includes_regular_neighbor() -> None:
    """BFS level-1 regular edge → neighbor appears in blast_radius."""
    conn = _make_bfs_db()
    blast, warnings = _run_bfs(conn, {"a"})
    blast_ids = {n.id for n in blast}
    assert "b" in blast_ids


def test_bfs_excludes_runtime_boundary_neighbor() -> None:
    """BFS RUNTIME_BOUNDARY edge → dst NOT in blast_radius."""
    conn = _make_bfs_db()
    blast, warnings = _run_bfs(conn, {"a"})
    blast_ids = {n.id for n in blast}
    assert "c" not in blast_ids


def test_bfs_runtime_boundary_produces_warning() -> None:
    """BFS RUNTIME_BOUNDARY edge → produces RuntimeBoundaryWarning."""
    conn = _make_bfs_db()
    blast, warnings = _run_bfs(conn, {"a"})
    assert len(warnings) == 1
    assert warnings[0].src_id == "a"
    assert warnings[0].dst_id == "c"
    assert warnings[0].src_name == "a_func"


def test_bfs_depth_exactly_two() -> None:
    """BFS traverses at most 2 hops from seeds."""
    conn = sqlite3.connect(":memory:")
    _seed_nodes(conn, [
        ("a", "a_f", "a.py", "function", 1, 2, None, None, "h"),
        ("b", "b_f", "b.py", "function", 1, 2, None, None, "h"),
        ("c", "c_f", "c.py", "function", 1, 2, None, None, "h"),
        ("d", "d_f", "d.py", "function", 1, 2, None, None, "h"),
    ])
    _seed_edges(conn, [
        ("a", "b", "LOCAL_CALL", "a.py"),
        ("b", "c", "LOCAL_CALL", "b.py"),
        ("c", "d", "LOCAL_CALL", "c.py"),  # 3 hops from a — must NOT appear
    ])
    conn.commit()

    blast, _ = _run_bfs(conn, {"a"})
    blast_ids = {n.id for n in blast}
    assert "b" in blast_ids
    assert "c" in blast_ids
    assert "d" not in blast_ids


# ---------------------------------------------------------------------------
# T039: hybrid_search — embed_model mismatch + zero results
# ---------------------------------------------------------------------------


def _make_hybrid_db(tmp_path, embed_model: str = "local") -> str:
    from cerebrofy.db.connection import open_db
    from cerebrofy.db.schema import create_schema

    db_path = tmp_path / "cerebrofy.db"
    conn = open_db(db_path)
    create_schema(conn, embed_dim=2)
    _seed_meta(conn, embed_model=embed_model)
    conn.commit()
    conn.close()
    return str(db_path)


def test_hybrid_search_embed_model_mismatch(tmp_path) -> None:
    """Different embed model in meta → ValueError raised before any query."""
    db_path = _make_hybrid_db(tmp_path, embed_model="model-a")

    class FakeCfg:
        embedding_model = "model-b"

    embedding = b"\x00" * 8  # 2 float32s = 8 bytes (not used, error fires first)

    with pytest.raises(ValueError, match="Embedding model mismatch"):
        hybrid_search(
            query="test",
            db_path=db_path,
            embedding=embedding,
            top_k=5,
            config_embed_model="model-b",
            lobe_dir=str(tmp_path),
        )


def test_hybrid_search_zero_results(tmp_path) -> None:
    """Mock _run_knn_query to return [] → HybridSearchResult with all empty fields."""
    db_path = _make_hybrid_db(tmp_path, embed_model="local")
    embedding = b"\x00" * 8

    with patch("cerebrofy.search.hybrid._run_knn_query", return_value=[]):
        result = hybrid_search(
            query="test",
            db_path=db_path,
            embedding=embedding,
            top_k=5,
            config_embed_model="local",
            lobe_dir=str(tmp_path),
        )

    assert result.matched_neurons == ()
    assert result.blast_radius == ()
    assert result.reindex_scope == 0
    assert result.search_duration_ms >= 0


# ---------------------------------------------------------------------------
# T055: SC-001 — hybrid_search BFS < 50ms on 1,000-node DB
# ---------------------------------------------------------------------------


def test_hybrid_search_bfs_under_50ms(tmp_path) -> None:
    """BFS + lobe resolution on 1,000 nodes completes in < 50ms (SC-001)."""
    from cerebrofy.db.connection import open_db
    from cerebrofy.db.schema import create_schema

    db_path = tmp_path / "cerebrofy.db"
    conn = open_db(db_path)
    create_schema(conn, embed_dim=2)
    _seed_meta(conn, embed_model="local")

    # Insert 1000 nodes
    nodes = [
        (f"file.py::func{i}", f"func{i}", "file.py", "function", i, i + 5, None, None, "h")
        for i in range(1000)
    ]
    conn.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", nodes)
    # Insert edges connecting every node to its successor (chain)
    edges = [
        (f"file.py::func{i}", f"file.py::func{i+1}", "LOCAL_CALL", "file.py")
        for i in range(999)
    ]
    conn.executemany("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?)", edges)
    conn.commit()
    conn.close()

    seed_neurons = [
        MatchedNeuron(id=f"file.py::func{i}", name=f"func{i}", file="file.py",
                      line_start=i, similarity=1.0 - i * 0.01)
        for i in range(10)
    ]

    with patch("cerebrofy.search.hybrid._run_knn_query", return_value=seed_neurons):
        result = hybrid_search(
            query="test",
            db_path=str(db_path),
            embedding=b"\x00" * 8,
            top_k=10,
            config_embed_model="local",
            lobe_dir=str(tmp_path),
        )

    assert result.search_duration_ms < 50, (
        f"BFS took {result.search_duration_ms:.1f}ms — exceeds SC-001 threshold of 50ms"
    )
