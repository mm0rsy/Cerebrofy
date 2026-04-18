"""DB write helpers: nodes, edges, vectors, file hashes, and build metadata."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from cerebrofy.graph.edges import Edge
from cerebrofy.parser.neuron import Neuron


class IgnoreMatcher(Protocol):
    def matches(self, path: str) -> bool: ...


def insert_meta(conn: sqlite3.Connection, embed_model: str, embed_dim: int) -> None:
    """Insert (or replace) the three initial meta rows for a fresh build."""
    rows = [
        ("schema_version", "1"),
        ("embed_model", embed_model),
        ("embed_dim", str(embed_dim)),
    ]
    conn.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", rows)


def write_nodes(conn: sqlite3.Connection, neurons: list[Neuron]) -> None:
    """Write Neurons to the nodes table (INSERT OR REPLACE)."""
    rows = []
    for n in neurons:
        node_hash = hashlib.sha256(
            f"{n.name}:{n.line_start}:{n.line_end}".encode()
        ).hexdigest()
        rows.append((
            n.id, n.name, n.file, n.type,
            n.line_start, n.line_end,
            n.signature, n.docstring, node_hash,
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO nodes"
        "(id,name,file,type,line_start,line_end,signature,docstring,hash)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def compute_file_hash(file_path: Path) -> str:
    """Return the SHA-256 hex digest of file_path's raw bytes."""
    content = file_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def compute_state_hash(file_hash_map: dict[str, str]) -> str:
    """Compute the deterministic state hash from per-file SHA-256 hashes.

    Formula: SHA-256(sorted per-file hashes joined by newlines).
    Sorting is on the hash values (not the file paths), matching db-schema.md.
    """
    joined = "\n".join(sorted(file_hash_map.values()))
    return hashlib.sha256(joined.encode()).hexdigest()


def collect_tracked_file_hashes(
    root: Path,
    tracked_extensions: Iterable[str],
    ignore_rules: IgnoreMatcher,
) -> dict[str, str]:
    """Collect tracked file hashes using the canonical build/update rules."""
    normalized_extensions = set(tracked_extensions)
    file_hash_map: dict[str, str] = {}
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = str(file_path.relative_to(root)).replace("\\", "/")
        if ignore_rules.matches(rel_path):
            continue
        if file_path.suffix.lower() not in normalized_extensions:
            continue
        file_hash_map[rel_path] = compute_file_hash(file_path)
    return file_hash_map


def write_file_hashes(conn: sqlite3.Connection, file_hash_map: dict[str, str]) -> None:
    """Write per-file SHA-256 hashes to file_hashes table (INSERT OR REPLACE)."""
    conn.executemany(
        "INSERT OR REPLACE INTO file_hashes(file, hash) VALUES (?, ?)",
        file_hash_map.items(),
    )


def write_build_meta(conn: sqlite3.Connection, state_hash: str) -> None:
    """Write state_hash and last_build timestamp to meta table."""
    rows = [
        ("state_hash", state_hash),
        ("last_build", datetime.utcnow().isoformat() + "Z"),
    ]
    conn.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", rows)


def write_edges(conn: sqlite3.Connection, edges: list[Edge]) -> None:
    """Write Edge objects to the edges table (INSERT OR IGNORE to avoid duplicates)."""
    conn.executemany(
        "INSERT OR IGNORE INTO edges(src_id, dst_id, rel_type, file) VALUES (?, ?, ?, ?)",
        [(e.src_id, e.dst_id, e.rel_type, e.file) for e in edges],
    )


def build_neuron_text(neuron: Neuron) -> str:
    """Build the text string sent to the embedding model for a Neuron."""
    text = f"{neuron.name}: {neuron.signature or ''} {neuron.docstring or ''}".strip()
    return text[:512]


def delete_nodes_for_files(
    conn: sqlite3.Connection, files: frozenset[str]
) -> set[str]:
    """Delete all nodes whose file is in files; return the set of deleted IDs."""
    if not files:
        return set()
    placeholders = ",".join("?" * len(files))
    rows = conn.execute(
        f"SELECT id FROM nodes WHERE file IN ({placeholders})", tuple(files)
    ).fetchall()
    deleted_ids = {row[0] for row in rows}
    conn.execute(
        f"DELETE FROM nodes WHERE file IN ({placeholders})", tuple(files)
    )
    return deleted_ids


def delete_edges_for_files(
    conn: sqlite3.Connection,
    files: frozenset[str],
    deleted_node_ids: set[str],
) -> None:
    """Delete edges for given files and orphaned edges referencing deleted node IDs."""
    if files:
        placeholders = ",".join("?" * len(files))
        conn.execute(
            f"DELETE FROM edges WHERE file IN ({placeholders})", tuple(files)
        )
    if deleted_node_ids:
        placeholders = ",".join("?" * len(deleted_node_ids))
        params = tuple(deleted_node_ids)
        conn.execute(
            f"DELETE FROM edges WHERE src_id IN ({placeholders}) OR dst_id IN ({placeholders})",
            params + params,
        )


def delete_vec_neurons(
    conn: sqlite3.Connection, node_ids: set[str]
) -> None:
    """Delete vec_neurons rows for the given node IDs (must be inside BEGIN IMMEDIATE)."""
    if not node_ids:
        return
    placeholders = ",".join("?" * len(node_ids))
    conn.execute(
        f"DELETE FROM vec_neurons WHERE id IN ({placeholders})", tuple(node_ids)
    )


def delete_file_hashes(
    conn: sqlite3.Connection, files: frozenset[str]
) -> None:
    """Delete file_hashes rows for the given file paths."""
    if not files:
        return
    placeholders = ",".join("?" * len(files))
    conn.execute(
        f"DELETE FROM file_hashes WHERE file IN ({placeholders})", tuple(files)
    )


def upsert_vectors(
    conn: sqlite3.Connection,
    neuron_ids: list[str],
    embeddings: list[list[float]],
) -> None:
    """Upsert embedding vectors into vec_neurons (INSERT OR REPLACE)."""
    conn.executemany(
        "INSERT OR REPLACE INTO vec_neurons(id, embedding) VALUES (?, vec_f32(?))",
        [(nid, json.dumps(emb)) for nid, emb in zip(neuron_ids, embeddings)],
    )
