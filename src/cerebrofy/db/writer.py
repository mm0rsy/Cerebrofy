"""DB write helpers: nodes, edges, vectors, file hashes, and build metadata."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def insert_meta(conn: sqlite3.Connection, embed_model: str, embed_dim: int) -> None:
    """Insert (or replace) the three initial meta rows for a fresh build."""
    rows = [
        ("schema_version", "1"),
        ("embed_model", embed_model),
        ("embed_dim", str(embed_dim)),
    ]
    conn.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", rows)


def write_nodes(conn: sqlite3.Connection, neurons: list) -> None:  # type: ignore[type-arg]
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


def write_edges(conn: sqlite3.Connection, edges: list) -> None:  # type: ignore[type-arg]
    """Write Edge objects to the edges table (INSERT OR IGNORE to avoid duplicates)."""
    conn.executemany(
        "INSERT OR IGNORE INTO edges(src_id, dst_id, rel_type, file) VALUES (?, ?, ?, ?)",
        [(e.src_id, e.dst_id, e.rel_type, e.file) for e in edges],
    )


def build_neuron_text(neuron: object) -> str:  # type: ignore[type-arg]
    """Build the text string sent to the embedding model for a Neuron."""
    from cerebrofy.parser.neuron import Neuron
    n: Neuron = neuron  # type: ignore[assignment]
    text = f"{n.name}: {n.signature or ''} {n.docstring or ''}".strip()
    return text[:512]


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
