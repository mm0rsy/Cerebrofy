"""Hybrid search: KNN cosine similarity + BFS depth-2 graph traversal."""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass

import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.graph.edges import RUNTIME_BOUNDARY


@dataclass(frozen=True)
class MatchedNeuron:
    """A Neuron returned by KNN cosine similarity search."""

    id: str
    name: str
    file: str
    line_start: int
    similarity: float


@dataclass(frozen=True)
class BlastRadiusNeuron:
    """A Neuron reachable within depth-2 BFS from matched neurons."""

    id: str
    name: str
    file: str
    line_start: int


@dataclass(frozen=True)
class RuntimeBoundaryWarning:
    """A RUNTIME_BOUNDARY edge encountered during BFS (never traversed)."""

    src_id: str
    src_name: str
    src_file: str
    dst_id: str
    lobe_name: str


@dataclass(frozen=True)
class HybridSearchResult:
    """Combined result from KNN search + BFS expansion."""

    query: str
    top_k: int
    matched_neurons: tuple[MatchedNeuron, ...]
    blast_radius: tuple[BlastRadiusNeuron, ...]
    affected_lobes: frozenset[str]
    affected_lobe_files: dict[str, str]
    runtime_boundary_warnings: tuple[RuntimeBoundaryWarning, ...]
    reindex_scope: int
    search_duration_ms: float


def _run_knn_query(
    conn: sqlite3.Connection, embedding: bytes, top_k: int
) -> list[MatchedNeuron]:
    """Two-step KNN query: vec0 distance search then nodes metadata fetch."""
    knn_rows = conn.execute(
        "SELECT id, distance FROM vec_neurons WHERE embedding MATCH ? AND k = ?",
        (embedding, top_k),
    ).fetchall()

    if not knn_rows:
        return []

    distance_map = {row[0]: row[1] for row in knn_rows}
    ids_placeholder = ",".join("?" * len(distance_map))
    node_rows = conn.execute(
        f"SELECT id, name, file, line_start FROM nodes WHERE id IN ({ids_placeholder})",
        list(distance_map.keys()),
    ).fetchall()

    neurons = [
        MatchedNeuron(
            id=row[0],
            name=row[1],
            file=row[2],
            line_start=row[3],
            similarity=1.0 - distance_map[row[0]] / 2.0,
        )
        for row in node_rows
    ]
    neurons.sort(key=lambda n: n.similarity, reverse=True)
    return neurons


def _expand_bfs_one_level(
    conn: sqlite3.Connection,
    current_ids: set[str],
    visited_ids: set[str],
) -> tuple[set[str], list[RuntimeBoundaryWarning]]:
    """Expand one BFS level from current_ids; collect RUNTIME_BOUNDARY warnings."""
    if not current_ids:
        return set(), []

    placeholder = ",".join("?" * len(current_ids))
    rows = conn.execute(
        f"SELECT src_id, dst_id, rel_type FROM edges WHERE src_id IN ({placeholder})",
        list(current_ids),
    ).fetchall()

    next_ids: set[str] = set()
    warnings: list[RuntimeBoundaryWarning] = []

    for src_id, dst_id, rel_type in rows:
        if rel_type == RUNTIME_BOUNDARY:
            warnings.append(RuntimeBoundaryWarning(
                src_id=src_id,
                src_name="",
                src_file="",
                dst_id=dst_id,
                lobe_name="",
            ))
        elif dst_id not in visited_ids:
            next_ids.add(dst_id)

    return next_ids, warnings


def _fetch_blast_radius_neurons(
    conn: sqlite3.Connection, node_ids: set[str]
) -> list[BlastRadiusNeuron]:
    """Fetch BlastRadiusNeuron records for the given node IDs."""
    if not node_ids:
        return []
    placeholder = ",".join("?" * len(node_ids))
    rows = conn.execute(
        f"SELECT id, name, file, line_start FROM nodes WHERE id IN ({placeholder})",
        list(node_ids),
    ).fetchall()
    return [BlastRadiusNeuron(id=r[0], name=r[1], file=r[2], line_start=r[3]) for r in rows]


def _run_bfs(
    conn: sqlite3.Connection, seed_ids: set[str]
) -> tuple[list[BlastRadiusNeuron], list[RuntimeBoundaryWarning]]:
    """Run exactly two BFS levels from seed_ids, excluding RUNTIME_BOUNDARY edges."""
    visited = seed_ids.copy()

    level1_ids, warnings1 = _expand_bfs_one_level(conn, seed_ids, visited)
    visited |= level1_ids

    level2_ids, warnings2 = _expand_bfs_one_level(conn, level1_ids, visited)
    visited |= level2_ids

    all_new_ids = (level1_ids | level2_ids) - seed_ids
    blast_neurons = _fetch_blast_radius_neurons(conn, all_new_ids)

    all_warnings = warnings1 + warnings2
    if all_warnings:
        warn_src_ids = {w.src_id for w in all_warnings}
        placeholder = ",".join("?" * len(warn_src_ids))
        src_rows = conn.execute(
            f"SELECT id, name, file FROM nodes WHERE id IN ({placeholder})",
            list(warn_src_ids),
        ).fetchall()
        src_meta = {r[0]: (r[1], r[2]) for r in src_rows}

        all_warnings = [
            RuntimeBoundaryWarning(
                src_id=w.src_id,
                src_name=src_meta.get(w.src_id, ("", ""))[0],
                src_file=src_meta.get(w.src_id, ("", ""))[1],
                dst_id=w.dst_id,
                lobe_name="",
            )
            for w in all_warnings
        ]

    return blast_neurons, all_warnings


def _resolve_affected_lobes(
    conn: sqlite3.Connection, node_ids: set[str], lobe_dir: str
) -> tuple[frozenset[str], dict[str, str]]:
    """Derive affected lobe names and their .md file paths from matched node IDs."""
    if not node_ids:
        return frozenset(), {}

    placeholder = ",".join("?" * len(node_ids))
    rows = conn.execute(
        f"SELECT DISTINCT file FROM nodes WHERE id IN ({placeholder})",
        list(node_ids),
    ).fetchall()

    lobe_files: dict[str, str] = {}
    for (file_path,) in rows:
        parts = file_path.split("/")
        lobe_name = parts[0] if len(parts) > 1 else "root"
        md_path = os.path.join(lobe_dir, f"{lobe_name}_lobe.md")
        if os.path.exists(md_path):
            lobe_files[lobe_name] = md_path

    return frozenset(lobe_files.keys()), lobe_files


def _embed_query(description: str, config: object) -> bytes:
    """Embed description using the configured embedder; return serialized float32 bytes."""
    from cerebrofy.embedder.base import Embedder

    embedding_model: str = getattr(config, "embedding_model", "local")
    if embedding_model == "local":
        from cerebrofy.embedder.local import LocalEmbedder
        embedder: Embedder = LocalEmbedder()
    elif embedding_model == "openai":
        from cerebrofy.embedder.openai_emb import OpenAIEmbedder
        embedder = OpenAIEmbedder()
    elif embedding_model == "cohere":
        from cerebrofy.embedder.cohere_emb import CohereEmbedder
        embedder = CohereEmbedder()
    else:
        from cerebrofy.embedder.local import LocalEmbedder
        embedder = LocalEmbedder()

    vector = embedder.embed([description])[0]
    result: bytes = sqlite_vec.serialize_float32(vector)
    return result


def hybrid_search(
    query: str,
    db_path: str,
    embedding: bytes,
    top_k: int,
    config_embed_model: str,
    lobe_dir: str,
) -> HybridSearchResult:
    """Run hybrid search: KNN + depth-2 BFS on a single read-only SQLite connection."""
    from pathlib import Path as _Path

    from cerebrofy.db.connection import open_db

    conn = open_db(_Path(db_path))

    try:
        meta_model_row = conn.execute(
            "SELECT value FROM meta WHERE key = 'embed_model'"
        ).fetchone()
        meta_model = meta_model_row[0] if meta_model_row else ""
        if meta_model != config_embed_model:
            raise ValueError(
                f"Embedding model mismatch: index was built with {meta_model}, "
                f"config says {config_embed_model}. Run 'cerebrofy build' to rebuild."
            )

        start = time.monotonic()
        matched_neurons = _run_knn_query(conn, embedding, top_k)

        if not matched_neurons:
            duration_ms = (time.monotonic() - start) * 1000
            return HybridSearchResult(
                query=query,
                top_k=top_k,
                matched_neurons=(),
                blast_radius=(),
                affected_lobes=frozenset(),
                affected_lobe_files={},
                runtime_boundary_warnings=(),
                reindex_scope=0,
                search_duration_ms=duration_ms,
            )

        seed_ids = {n.id for n in matched_neurons}
        blast_radius, warnings = _run_bfs(conn, seed_ids)
        all_ids = seed_ids | {n.id for n in blast_radius}
        affected_lobes, lobe_files = _resolve_affected_lobes(conn, all_ids, lobe_dir)
        duration_ms = (time.monotonic() - start) * 1000

    finally:
        conn.close()

    return HybridSearchResult(
        query=query,
        top_k=top_k,
        matched_neurons=tuple(matched_neurons),
        blast_radius=tuple(blast_radius),
        affected_lobes=affected_lobes,
        affected_lobe_files=lobe_files,
        runtime_boundary_warnings=tuple(warnings),
        reindex_scope=len(matched_neurons) + len(blast_radius),
        search_duration_ms=duration_ms,
    )
