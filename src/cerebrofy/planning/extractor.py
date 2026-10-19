"""Cohesive neuron-cluster identification for refactor plans (Idea #12).

Two-phase detection:
  1. Semantic seed — reuse the KNN query from ``cerebrofy.search.hybrid``.
  2. Cluster expansion — keep graph neighbors whose incident edges are
     predominantly (>50% by default) internal to the cluster.

Law V: detection uses graph data only — zero language-specific logic.

Requires a completed ``cerebrofy build`` index (a read-only connection with
sqlite-vec loaded, e.g. via ``cerebrofy.search.hybrid._open_ro``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cerebrofy.graph.edges import RUNTIME_BOUNDARY
from cerebrofy.search.hybrid import _fetch_nodes_by_ids, _knn_search

# Default KNN seed size (spec: k=20).
DEFAULT_TOP_K = 20
# A candidate joins the cluster when strictly more than half of its incident
# edges connect it to cluster members (spec: internal/total > 0.5).
DEFAULT_INTERNAL_EDGE_RATIO = 0.5
# Spec error bound: more than 200 matched neurons → CLUSTER_TOO_LARGE.
# Per Idea #12 acceptance criteria — Error Codes table defines
# CLUSTER_TOO_LARGE as "More than 200 neurons matched".
# Source: .ideas/12-natural-language-refactor-planner/IDEA.md (Error Codes).
MAX_CLUSTER_SIZE = 200
# Spec error bound: fewer than 2 matched neurons → CLUSTER_TOO_SMALL.
# Per Idea #12 acceptance criteria — Error Codes table defines
# CLUSTER_TOO_SMALL as "Fewer than 2 neurons matched the description".
# Source: .ideas/12-natural-language-refactor-planner/IDEA.md (Error Codes).
MIN_CLUSTER_SIZE = 2


class ClusterSizeError(Exception):
    """Raised when the matched cluster falls outside the supported size range."""

    def __init__(self, size: int) -> None:
        super().__init__(
            f"cluster size {size} is outside {MIN_CLUSTER_SIZE}..{MAX_CLUSTER_SIZE}"
        )
        self.size = size


@dataclass(frozen=True)
class ClusterNeuron:
    """One neuron participating in a refactor plan."""

    id: str
    name: str
    file: str
    line_start: int | None
    line_end: int | None
    # KNN cosine similarity for seeds; internal-edge ratio for expansion neurons.
    relevance_score: float


@dataclass
class NeuronCluster:
    """Result of cluster detection for one refactoring description."""

    seeds: list[ClusterNeuron]              # KNN hits, sorted by similarity desc
    neurons: list[ClusterNeuron]            # seeds + expansion, deterministic order
    external_callers: list[ClusterNeuron]   # callers outside the cluster
    runtime_boundary_callers: list[str]     # caller ids behind RUNTIME_BOUNDARY edges


# ---------------------------------------------------------------------------
# Phase 1: semantic seed
# ---------------------------------------------------------------------------

def knn_seeds(
    conn: sqlite3.Connection,
    embedding: list[float],
    top_k: int = DEFAULT_TOP_K,
) -> list[ClusterNeuron]:
    """Return KNN hits with similarity > 0, sorted by similarity desc."""
    hits = [(nid, sim) for nid, sim in _knn_search(conn, embedding, top_k) if sim > 0.0]
    nodes = _fetch_nodes_by_ids(conn, [nid for nid, _ in hits])
    seeds: list[ClusterNeuron] = []
    for nid, sim in hits:
        node = nodes.get(nid)
        if node is None:
            continue  # vec row without a node row — skip defensively
        seeds.append(ClusterNeuron(
            id=nid,
            name=node["name"] or "",
            file=node["file"] or "",
            line_start=node["line_start"],
            line_end=node["line_end"],
            relevance_score=sim,
        ))
    return seeds


# ---------------------------------------------------------------------------
# Phase 2: cluster expansion
# ---------------------------------------------------------------------------

def _in_clause_placeholders(count: int) -> str:
    return ",".join("?" * count)


def _filter_existing_node_ids(conn: sqlite3.Connection, ids: set[str]) -> set[str]:
    """Filter *ids* down to those that exist in the nodes table."""
    if not ids:
        return set()
    ordered = sorted(ids)
    rows = conn.execute(
        f"SELECT id FROM nodes WHERE id IN ({_in_clause_placeholders(len(ordered))})",
        ordered,
    ).fetchall()
    return {row[0] for row in rows}


def _collect_cluster_neighbors(conn: sqlite3.Connection, cluster_ids: set[str]) -> set[str]:
    """Return all edge endpoints adjacent to the cluster (excluding the cluster).

    RUNTIME_BOUNDARY edges are never traversed (Law II).
    """
    if not cluster_ids:
        return set()
    ordered = sorted(cluster_ids)
    ph = _in_clause_placeholders(len(ordered))
    rows = conn.execute(
        f"SELECT src_id, dst_id FROM edges "
        f"WHERE (src_id IN ({ph}) OR dst_id IN ({ph})) AND rel_type != ?",
        [*ordered, *ordered, RUNTIME_BOUNDARY],
    ).fetchall()
    neighbors: set[str] = set()
    for src_id, dst_id in rows:
        if src_id not in cluster_ids:
            neighbors.add(src_id)
        if dst_id not in cluster_ids:
            neighbors.add(dst_id)
    return neighbors


def _edge_counts(
    conn: sqlite3.Connection,
    node_id: str,
    cluster_ids: set[str],
) -> tuple[int, int]:
    """Return (internal_edges, total_edges) for *node_id*.

    Internal = non-RUNTIME_BOUNDARY edges between *node_id* and cluster members
    (either direction). Total = all non-RUNTIME_BOUNDARY incident edges.
    """
    total_row = conn.execute(
        "SELECT COUNT(*) FROM edges "
        "WHERE (src_id = ? OR dst_id = ?) AND rel_type != ?",
        (node_id, node_id, RUNTIME_BOUNDARY),
    ).fetchone()
    total = int(total_row[0]) if total_row else 0

    ordered = sorted(cluster_ids)
    ph = _in_clause_placeholders(len(ordered))
    internal_row = conn.execute(
        f"SELECT COUNT(*) FROM edges WHERE rel_type != ? AND ("
        f"(src_id = ? AND dst_id IN ({ph})) OR (dst_id = ? AND src_id IN ({ph})))",
        [RUNTIME_BOUNDARY, node_id, *ordered, node_id, *ordered],
    ).fetchone()
    internal = int(internal_row[0]) if internal_row else 0
    return internal, total


def expand_cluster(
    conn: sqlite3.Connection,
    seeds: list[ClusterNeuron],
    *,
    internal_ratio: float = DEFAULT_INTERNAL_EDGE_RATIO,
    max_size: int = MAX_CLUSTER_SIZE,
) -> list[ClusterNeuron]:
    """Expand *seeds* with densely connected neighbors (fixpoint, deterministic).

    A candidate joins when ``internal_edges / total_edges > internal_ratio``.
    Candidates are visited in sorted-id order so the result is deterministic.
    Raises ClusterSizeError when the cluster would exceed *max_size*.
    """
    cluster: dict[str, ClusterNeuron] = {seed.id: seed for seed in seeds}

    while True:
        members = set(cluster)
        candidates = _filter_existing_node_ids(
            conn, _collect_cluster_neighbors(conn, members)
        ) - members
        added = False
        for candidate_id in sorted(candidates):
            internal, total = _edge_counts(conn, candidate_id, set(cluster))
            if total <= 0 or internal / total <= internal_ratio:
                continue
            if len(cluster) >= max_size:
                raise ClusterSizeError(len(cluster) + 1)
            rows = _fetch_nodes_by_ids(conn, [candidate_id])
            node = rows.get(candidate_id)
            if node is None:
                continue
            cluster[candidate_id] = ClusterNeuron(
                id=candidate_id,
                name=node["name"] or "",
                file=node["file"] or "",
                line_start=node["line_start"],
                line_end=node["line_end"],
                relevance_score=round(internal / total, 4),
            )
            added = True
        if not added:
            break

    expansion = sorted(
        (n for n in cluster.values() if n.id not in {s.id for s in seeds}),
        key=lambda n: (n.file, n.line_start if n.line_start is not None else 0, n.name),
    )
    return list(seeds) + expansion


# ---------------------------------------------------------------------------
# External callers
# ---------------------------------------------------------------------------

def _fetch_callers(
    conn: sqlite3.Connection,
    src_ids: set[str],
) -> list[ClusterNeuron]:
    """Resolve caller ids to ClusterNeurons, sorted by (file, line, name)."""
    present = _filter_existing_node_ids(conn, src_ids)
    nodes = _fetch_nodes_by_ids(conn, sorted(present))
    callers = [
        ClusterNeuron(
            id=nid,
            name=node["name"] or "",
            file=node["file"] or "",
            line_start=node["line_start"],
            line_end=node["line_end"],
            relevance_score=0.0,
        )
        for nid, node in nodes.items()
    ]
    callers.sort(key=lambda n: (n.file, n.line_start if n.line_start is not None else 0, n.name))
    return callers


def find_external_callers(
    conn: sqlite3.Connection,
    cluster_ids: set[str],
) -> list[ClusterNeuron]:
    """Return direct callers outside the cluster that must be updated.

    RUNTIME_BOUNDARY edges are excluded (reported separately — Law II).
    """
    if not cluster_ids:
        return []
    ordered = sorted(cluster_ids)
    rows = conn.execute(
        f"SELECT DISTINCT src_id FROM edges "
        f"WHERE dst_id IN ({_in_clause_placeholders(len(ordered))}) AND src_id NOT IN ({_in_clause_placeholders(len(ordered))}) AND rel_type != ?",
        [*ordered, *ordered, RUNTIME_BOUNDARY],
    ).fetchall()
    return _fetch_callers(conn, {row[0] for row in rows})


def find_runtime_boundary_callers(
    conn: sqlite3.Connection,
    cluster_ids: set[str],
) -> list[str]:
    """Return caller ids that reach the cluster only through RUNTIME_BOUNDARY edges."""
    if not cluster_ids:
        return []
    ordered = sorted(cluster_ids)
    rows = conn.execute(
        f"SELECT DISTINCT src_id FROM edges WHERE dst_id IN ({_in_clause_placeholders(len(ordered))}) AND rel_type = ?",
        [*ordered, RUNTIME_BOUNDARY],
    ).fetchall()
    return sorted(row[0] for row in rows)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def find_extraction_cluster(
    conn: sqlite3.Connection,
    embedding: list[float],
    top_k: int = DEFAULT_TOP_K,
    *,
    internal_ratio: float = DEFAULT_INTERNAL_EDGE_RATIO,
) -> NeuronCluster:
    """Identify the cohesive neuron cluster for a refactoring description.

    Raises ClusterSizeError when fewer than 2 seeds match (CLUSTER_TOO_SMALL)
    or the seed/cluster size exceeds 200 (CLUSTER_TOO_LARGE).
    """
    seeds = knn_seeds(conn, embedding, top_k=top_k)
    if len(seeds) > MAX_CLUSTER_SIZE:
        raise ClusterSizeError(len(seeds))
    if len(seeds) < MIN_CLUSTER_SIZE:
        raise ClusterSizeError(len(seeds))

    neurons = expand_cluster(conn, seeds, internal_ratio=internal_ratio)
    cluster_ids = {n.id for n in neurons}
    return NeuronCluster(
        seeds=seeds,
        neurons=neurons,
        external_callers=find_external_callers(conn, cluster_ids),
        runtime_boundary_callers=find_runtime_boundary_callers(conn, cluster_ids),
    )
