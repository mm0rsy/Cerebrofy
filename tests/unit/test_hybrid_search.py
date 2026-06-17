"""Unit tests for cerebrofy.search.hybrid — KNN + BFS hybrid search engine."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.db.schema import create_schema
from cerebrofy.search.hybrid import (
    HybridSearchResult,
    RuntimeBoundaryWarning,
    _resolve_lobe,
    embed_query,
    hybrid_search,
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path, embed_dim: int = 4) -> Path:
    """Create a real cerebrofy.db under tmp_path with sqlite-vec loaded."""
    db_path = tmp_path / "cerebrofy.db"
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    create_schema(conn, embed_dim=embed_dim)
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    conn.commit()
    conn.close()
    return db_path


def _insert_node(
    conn: sqlite3.Connection,
    nid: str,
    name: str = "fn",
    file: str = "src/main.py",
    ntype: str = "function",
    line_start: int = 1,
    line_end: int = 10,
    signature: str | None = None,
    docstring: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO nodes(id, name, file, type, line_start, line_end, signature, docstring)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (nid, name, file, ntype, line_start, line_end, signature, docstring),
    )


def _insert_vec(conn: sqlite3.Connection, nid: str, embedding: list[float]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO vec_neurons(id, embedding) VALUES (?, vec_f32(?))",
        (nid, json.dumps(embedding)),
    )


def _insert_edge(
    conn: sqlite3.Connection,
    src_id: str,
    dst_id: str,
    rel_type: str = "LOCAL_CALL",
    file: str = "src/main.py",
) -> None:
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, rel_type, file) VALUES (?, ?, ?, ?)",
        (src_id, dst_id, rel_type, file),
    )


def _open_rw(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-write with sqlite-vec loaded (for test data insertion)."""
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


# ---------------------------------------------------------------------------
# Test 1: embed_query raises for 'none' model
# ---------------------------------------------------------------------------

def test_embed_query_raises_for_none_model() -> None:
    """embed_query('q', 'none') must raise ValueError immediately."""
    with pytest.raises(ValueError, match="none"):
        embed_query("what does the auth module do?", "none")


# ---------------------------------------------------------------------------
# Test 2: empty index → empty HybridSearchResult
# ---------------------------------------------------------------------------

def test_hybrid_search_empty_index(tmp_path: Path) -> None:
    """An empty vec_neurons table returns an empty HybridSearchResult."""
    db_path = _make_db(tmp_path)
    # No nodes or vectors inserted.
    result = hybrid_search(
        query="something",
        db_path=db_path,
        embedding=[0.1, 0.2, 0.3, 0.4],
        top_k=10,
    )
    assert isinstance(result, HybridSearchResult)
    assert result.matched_neurons == []
    assert result.blast_radius == []
    assert result.runtime_boundary_warnings == []
    assert result.affected_lobes == []


# ---------------------------------------------------------------------------
# Test 3: KNN returns top_k results sorted by similarity desc
# ---------------------------------------------------------------------------

def test_hybrid_search_knn_returns_top_k(tmp_path: Path) -> None:
    """Insert 5 vectors, query with top_k=3 — exactly 3 results, sorted by similarity desc."""
    db_path = _make_db(tmp_path)
    conn = _open_rw(db_path)

    # Five nodes with embeddings at increasing angles from [1,0,0,0]
    nodes = [
        ("n1", [1.0, 0.0, 0.0, 0.0]),   # identical to query → distance ~0
        ("n2", [0.9, 0.1, 0.0, 0.0]),
        ("n3", [0.7, 0.3, 0.0, 0.0]),
        ("n4", [0.4, 0.6, 0.0, 0.0]),
        ("n5", [0.0, 1.0, 0.0, 0.0]),   # most distant
    ]
    for nid, emb in nodes:
        _insert_node(conn, nid, name=f"func_{nid}", file=f"src/{nid}.py")
        _insert_vec(conn, nid, emb)
    conn.commit()
    conn.close()

    result = hybrid_search(
        query="test",
        db_path=db_path,
        embedding=[1.0, 0.0, 0.0, 0.0],
        top_k=3,
    )

    assert len(result.matched_neurons) == 3

    # Results must be sorted by similarity descending
    sims = [n.similarity for n in result.matched_neurons]
    assert sims == sorted(sims, reverse=True), f"Not sorted desc: {sims}"

    # The closest node (n1) should be first
    assert result.matched_neurons[0].id == "n1"
    # All similarities must be in [0, 1]
    for neuron in result.matched_neurons:
        assert 0.0 <= neuron.similarity <= 1.0


# ---------------------------------------------------------------------------
# Test 4: BFS follows LOCAL_CALL edges and adds neighbors to blast_radius
# ---------------------------------------------------------------------------

def test_hybrid_search_bfs_follows_edges(tmp_path: Path) -> None:
    """KNN hits 1 neuron; 2 neighbors via LOCAL_CALL → both appear in blast_radius."""
    db_path = _make_db(tmp_path)
    conn = _open_rw(db_path)

    # Seed neuron (in vec_neurons so KNN finds it)
    _insert_node(conn, "seed", name="seed_fn", file="src/seed.py")
    _insert_vec(conn, "seed", [1.0, 0.0, 0.0, 0.0])

    # Neighbors (in nodes but NOT in vec_neurons)
    _insert_node(conn, "neighbor_a", name="fn_a", file="src/a.py")
    _insert_node(conn, "neighbor_b", name="fn_b", file="src/b.py")

    # Edges: seed → neighbor_a, neighbor_b → seed (both LOCAL_CALL)
    _insert_edge(conn, "seed", "neighbor_a", rel_type="LOCAL_CALL")
    _insert_edge(conn, "neighbor_b", "seed", rel_type="LOCAL_CALL")
    conn.commit()
    conn.close()

    result = hybrid_search(
        query="test",
        db_path=db_path,
        embedding=[1.0, 0.0, 0.0, 0.0],
        top_k=5,
    )

    assert len(result.matched_neurons) == 1
    assert result.matched_neurons[0].id == "seed"

    blast_ids = {n.id for n in result.blast_radius}
    assert "neighbor_a" in blast_ids
    assert "neighbor_b" in blast_ids

    # Blast-radius nodes have similarity=0.0
    for neuron in result.blast_radius:
        assert neuron.similarity == 0.0


# ---------------------------------------------------------------------------
# Test 5: BFS skips RUNTIME_BOUNDARY edges → warnings, not blast_radius
# ---------------------------------------------------------------------------

def test_hybrid_search_bfs_skips_runtime_boundary(tmp_path: Path) -> None:
    """RUNTIME_BOUNDARY edge appears in warnings and NOT in blast_radius."""
    db_path = _make_db(tmp_path)
    conn = _open_rw(db_path)

    _insert_node(conn, "seed", name="seed_fn", file="src/seed.py")
    _insert_vec(conn, "seed", [1.0, 0.0, 0.0, 0.0])

    _insert_node(conn, "rt_neighbor", name="rt_fn", file="src/runtime.py")
    _insert_edge(conn, "seed", "rt_neighbor", rel_type="RUNTIME_BOUNDARY")

    conn.commit()
    conn.close()

    result = hybrid_search(
        query="test",
        db_path=db_path,
        embedding=[1.0, 0.0, 0.0, 0.0],
        top_k=5,
    )

    # rt_neighbor must NOT be in blast_radius
    blast_ids = {n.id for n in result.blast_radius}
    assert "rt_neighbor" not in blast_ids

    # Must appear as a RuntimeBoundaryWarning
    assert len(result.runtime_boundary_warnings) == 1
    warning = result.runtime_boundary_warnings[0]
    assert isinstance(warning, RuntimeBoundaryWarning)
    assert warning.src_id == "seed"
    assert warning.dst_id == "rt_neighbor"


# ---------------------------------------------------------------------------
# Test 6: affected_lobes resolved correctly
# ---------------------------------------------------------------------------

def test_hybrid_search_affected_lobes(tmp_path: Path) -> None:
    """Neurons in src/auth/ with lobe {'auth': 'src/auth'} → affected_lobes == ['auth']."""
    db_path = _make_db(tmp_path)
    conn = _open_rw(db_path)

    _insert_node(conn, "auth1", name="login", file="src/auth/login.py")
    _insert_vec(conn, "auth1", [1.0, 0.0, 0.0, 0.0])

    _insert_node(conn, "auth2", name="logout", file="src/auth/logout.py")
    _insert_vec(conn, "auth2", [0.9, 0.1, 0.0, 0.0])

    conn.commit()
    conn.close()

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = hybrid_search(
        query="test",
        db_path=db_path,
        embedding=[1.0, 0.0, 0.0, 0.0],
        top_k=10,
        lobes={"auth": "src/auth"},
        repo_root=repo_root,
    )

    assert result.affected_lobes == ["auth"]


# ---------------------------------------------------------------------------
# Test 7: _resolve_lobe returns None for unmatched files
# ---------------------------------------------------------------------------

def test_resolve_lobe_returns_none_for_unmatched(tmp_path: Path) -> None:
    """A file not under any lobe directory → _resolve_lobe returns None."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    lobes = {"auth": "src/auth", "billing": "src/billing"}
    result = _resolve_lobe("src/utils/helpers.py", lobes, repo_root)
    assert result is None


def test_resolve_lobe_matches_correct_lobe(tmp_path: Path) -> None:
    """A file under src/auth/ → _resolve_lobe returns 'auth'."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    lobes = {"auth": "src/auth", "billing": "src/billing"}
    result = _resolve_lobe("src/auth/login.py", lobes, repo_root)
    assert result == "auth"


def test_resolve_lobe_handles_absolute_path(tmp_path: Path) -> None:
    """An absolute file path matching a lobe directory → correct lobe returned."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src" / "auth").mkdir(parents=True)

    abs_file = str(repo_root / "src" / "auth" / "session.py")
    lobes = {"auth": "src/auth"}
    result = _resolve_lobe(abs_file, lobes, repo_root)
    assert result == "auth"
