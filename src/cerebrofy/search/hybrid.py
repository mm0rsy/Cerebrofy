"""Hybrid KNN + BFS search engine for Cerebrofy.

Two-phase pipeline:
  Phase 1 (KNN): embed the query → find top-K neurons by cosine similarity via sqlite-vec.
  Phase 2 (BFS): traverse the call graph outward depth-2 from KNN hits, skipping
                  RUNTIME_BOUNDARY edges (collected as warnings).

Invariants:
  - Embed query BEFORE opening the DB connection.
  - KNN query and BFS traversal share a single read-only sqlite3.Connection.
  - RUNTIME_BOUNDARY edges are never traversed; they become RuntimeBoundaryWarning items.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.graph.edges import RUNTIME_BOUNDARY


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchedNeuron:
    """A neuron returned by KNN (similarity > 0) or BFS (similarity = 0.0)."""

    id: str
    name: str
    type: str
    file: str
    line_start: int | None
    line_end: int | None
    signature: str | None
    docstring: str | None
    similarity: float  # 0.0–1.0; 0.0 for blast-radius nodes


@dataclass(frozen=True)
class RuntimeBoundaryWarning:
    """An edge that was skipped during BFS because its rel_type is RUNTIME_BOUNDARY."""

    src_id: str
    dst_id: str


@dataclass
class HybridSearchResult:
    """Result of a hybrid KNN + BFS search."""

    query: str
    matched_neurons: list[MatchedNeuron]  # KNN hits, sorted by similarity desc
    blast_radius: list[MatchedNeuron]     # BFS neighbors not in matched_neurons
    runtime_boundary_warnings: list[RuntimeBoundaryWarning]
    affected_lobes: list[str]             # sorted, deduplicated


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension on *conn*."""
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def _check_schema_version(conn: sqlite3.Connection, expected: int = 1) -> None:
    """Assert the schema version matches *expected*, or raise ValueError."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None or int(row[0]) != expected:
        got = row[0] if row is not None else None
        raise ValueError(f"Schema version mismatch: expected {expected}, got {got}")


def _open_ro(db_path: Path) -> sqlite3.Connection:
    """Open cerebrofy.db read-only with sqlite-vec loaded and schema version verified."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    _load_sqlite_vec(conn)
    _check_schema_version(conn)
    return conn


def _resolve_lobe(file: str, lobes: dict[str, str], repo_root: Path) -> str | None:
    """Return the lobe name whose directory contains *file*, or None if unmatched."""
    file_path = Path(file)
    if not file_path.is_absolute():
        file_path = repo_root / file_path
    for lobe_name, lobe_dir in lobes.items():
        try:
            file_path.relative_to(repo_root / lobe_dir)
            return lobe_name
        except ValueError:
            continue
    return None


def _fetch_nodes_by_ids(
    conn: sqlite3.Connection, node_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Fetch node rows for the given IDs. Returns a dict keyed by id."""
    if not node_ids:
        return {}
    placeholders = ",".join("?" * len(node_ids))
    rows = conn.execute(
        f"SELECT id, name, type, file, line_start, line_end, signature, docstring "
        f"FROM nodes WHERE id IN ({placeholders})",
        node_ids,
    ).fetchall()
    return {
        row[0]: {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "file": row[3],
            "line_start": row[4],
            "line_end": row[5],
            "signature": row[6],
            "docstring": row[7],
        }
        for row in rows
    }


def _make_matched_neuron(node: dict[str, Any], similarity: float) -> MatchedNeuron:
    return MatchedNeuron(
        id=node["id"],
        name=node["name"] or "",
        type=node["type"] or "",
        file=node["file"] or "",
        line_start=node["line_start"],
        line_end=node["line_end"],
        signature=node["signature"],
        docstring=node["docstring"],
        similarity=similarity,
    )


# ---------------------------------------------------------------------------
# Phase 1: KNN
# ---------------------------------------------------------------------------

def _knn_search(
    conn: sqlite3.Connection, embedding: list[float], top_k: int
) -> list[tuple[str, float]]:
    """Run the vec_neurons KNN query. Returns [(id, similarity), ...] sorted desc."""
    param = json.dumps(embedding)
    rows = conn.execute(
        "SELECT id, distance FROM vec_neurons "
        "WHERE embedding MATCH vec_f32(?) "
        "ORDER BY distance LIMIT ?",
        (param, top_k),
    ).fetchall()
    results = []
    for nid, distance in rows:
        similarity = max(0.0, 1.0 - distance)
        results.append((nid, similarity))
    return results


# ---------------------------------------------------------------------------
# Phase 2: BFS depth-2
# ---------------------------------------------------------------------------

def _bfs_depth2(
    conn: sqlite3.Connection,
    seed_ids: set[str],
) -> tuple[set[str], list[RuntimeBoundaryWarning]]:
    """BFS outward from *seed_ids* for 2 hops through non-RUNTIME_BOUNDARY edges.

    Returns (neighbor_ids, warnings) where neighbor_ids excludes seed_ids.
    """
    warnings: list[RuntimeBoundaryWarning] = []
    visited: set[str] = set(seed_ids)
    frontier: set[str] = set(seed_ids)
    discovered: set[str] = set()

    for _depth in range(2):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        rows = conn.execute(
            f"SELECT src_id, dst_id, rel_type FROM edges "
            f"WHERE src_id IN ({placeholders}) OR dst_id IN ({placeholders})",
            list(frontier) + list(frontier),
        ).fetchall()

        next_frontier: set[str] = set()
        for src_id, dst_id, rel_type in rows:
            if rel_type == RUNTIME_BOUNDARY:
                warnings.append(RuntimeBoundaryWarning(src_id=src_id, dst_id=dst_id))
                continue
            for neighbor in (src_id, dst_id):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
                    discovered.add(neighbor)

        frontier = next_frontier

    return discovered, warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed_query(query: str, embedding_model: str) -> list[float]:
    """Embed a plain-language query using the configured model.

    Raises ValueError if embedding_model is 'none' (no embedder configured).
    """
    if embedding_model == "none":
        raise ValueError(
            "embedding_model is 'none' — cannot embed query. "
            "Configure a valid embedding model in config.yaml."
        )
    from cerebrofy.embedder import get_embedder
    embedder = get_embedder(embedding_model)
    if embedder is None:
        raise ValueError(
            f"No embedder available for model {embedding_model!r}."
        )
    vectors = embedder.embed([query])
    return vectors[0]


def hybrid_search(
    query: str,
    db_path: Path | str,
    embedding: list[float],
    top_k: int = 10,
    *,
    lobes: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> HybridSearchResult:
    """Run KNN + BFS search against cerebrofy.db.

    Opens a single read-only connection shared by both phases.
    The *embedding* must be pre-computed (call embed_query() first).

    Args:
        query: The original query string (stored on the result for reference).
        db_path: Path to cerebrofy.db.
        embedding: Pre-computed query embedding (384-dim for bge-small-en-v1.5).
        top_k: Maximum number of KNN results to return.
        lobes: Lobe name → directory path mapping (from config.lobes).
        repo_root: Repository root for resolving relative file paths.

    Returns:
        HybridSearchResult with matched_neurons, blast_radius,
        runtime_boundary_warnings, and affected_lobes.
    """
    db_path = Path(db_path)
    lobes = lobes or {}
    repo_root = repo_root or Path.cwd()

    conn = _open_ro(db_path)
    try:
        # Phase 1: KNN
        knn_hits = _knn_search(conn, embedding, top_k)
        knn_ids = [nid for nid, _ in knn_hits]

        # Fetch node details for KNN hits
        knn_nodes = _fetch_nodes_by_ids(conn, knn_ids)

        matched_neurons: list[MatchedNeuron] = []
        for nid, sim in knn_hits:
            node = knn_nodes.get(nid)
            if node is None:
                continue
            matched_neurons.append(_make_matched_neuron(node, sim))

        # Phase 2: BFS depth-2
        seed_set = set(knn_ids)
        bfs_neighbor_ids, rb_warnings = _bfs_depth2(conn, seed_set)

        # Fetch node details for BFS neighbors
        bfs_nodes = _fetch_nodes_by_ids(conn, list(bfs_neighbor_ids))

        blast_radius: list[MatchedNeuron] = []
        for nid, node in bfs_nodes.items():
            blast_radius.append(_make_matched_neuron(node, 0.0))

    finally:
        conn.close()

    # Resolve affected lobes from both matched_neurons and blast_radius
    affected_lobe_set: set[str] = set()
    for neuron in matched_neurons + blast_radius:
        if neuron.file and lobes:
            lobe = _resolve_lobe(neuron.file, lobes, repo_root)
            if lobe is not None:
                affected_lobe_set.add(lobe)

    return HybridSearchResult(
        query=query,
        matched_neurons=matched_neurons,
        blast_radius=blast_radius,
        runtime_boundary_warnings=rb_warnings,
        affected_lobes=sorted(affected_lobe_set),
    )
