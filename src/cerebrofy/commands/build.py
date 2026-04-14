"""cerebrofy build — 6-step atomic pipeline orchestrator."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import click

from cerebrofy.config.loader import CerebrоfyConfig, load_config
from cerebrofy.db.connection import check_schema_version, open_db
from cerebrofy.db.lock import BuildLock, acquire, is_stale, release
from cerebrofy.db.schema import create_schema
from cerebrofy.db.writer import (
    build_neuron_text,
    collect_tracked_file_hashes,
    compute_state_hash,
    insert_meta,
    upsert_vectors,
    write_build_meta,
    write_edges,
    write_file_hashes,
    write_nodes,
)
from cerebrofy.embedder import get_embedder
from cerebrofy.embedder.base import Embedder
from cerebrofy.graph.edges import Edge
from cerebrofy.graph.resolver import (
    build_name_registry,
    resolve_cross_module_edges,
    resolve_import_edges,
    resolve_local_edges,
)
from cerebrofy.ignore.ruleset import IgnoreRuleSet
from cerebrofy.markdown.lobe import write_lobe_md
from cerebrofy.markdown.map import write_map_md
from cerebrofy.parser.engine import parse_directory
from cerebrofy.parser.neuron import Neuron, ParseResult


def get_tmp_path(db_path: Path) -> Path:
    """Return the .tmp sibling path used during an in-progress build."""
    return db_path.parent / (db_path.name + ".tmp")


def cleanup_stale_tmp(tmp_path: Path) -> None:
    """Delete tmp_path if it exists; silently ignore FileNotFoundError."""
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass


def build_step0_create_db(db_path: Path, embed_model: str, embed_dim: int) -> sqlite3.Connection:
    """Step 0: Create the .tmp database, apply schema, write initial meta rows.

    Always writes to get_tmp_path(db_path). The atomic swap to db_path happens in
    cerebrofy_build after all steps succeed.
    """
    click.echo("Cerebrofy: Step 0/6 — Creating index database")
    tmp_path = get_tmp_path(db_path)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.unlink(missing_ok=True)
    conn = open_db(tmp_path)
    create_schema(conn, embed_dim)
    insert_meta(conn, embed_model, embed_dim)
    return conn


def build_step1_parse(
    root: Path,
    config: CerebrоfyConfig,
    ignore_rules: IgnoreRuleSet,
) -> list[ParseResult]:
    """Step 1: Parse all tracked source files and return ParseResult list."""
    # Pre-scan to know N before the batch call (two-print contract from spec)
    tracked_files = [
        f for f in sorted(root.rglob("*"))
        if f.is_file()
        and not ignore_rules.matches(str(f.relative_to(root)).replace("\\", "/"))
        and f.suffix.lower() in config.tracked_extensions
    ]
    n = len(tracked_files)

    queries_dir = root / ".cerebrofy" / "queries"
    click.echo(f"Cerebrofy: Step 1/6 — Parsing source files (0 / {n} files)")
    parse_results = parse_directory(root, config, ignore_rules, queries_dir=queries_dir)
    click.echo(f"Cerebrofy: Step 1/6 — Parsing source files ({n} / {n} files)")

    for pr in parse_results:
        for warning in pr.warnings:
            click.echo(f"Warning: {warning}", err=True)

    return parse_results


def build_step5_commit(
    conn: sqlite3.Connection,
    root: Path,
    config: CerebrоfyConfig,
    ignore_rules: IgnoreRuleSet,
) -> str:
    """Step 5: Compute file hashes, write state_hash + last_build, commit."""
    file_hash_map = collect_tracked_file_hashes(
        root,
        config.tracked_extensions,
        ignore_rules,
    )
    write_file_hashes(conn, file_hash_map)
    state_hash = compute_state_hash(file_hash_map)
    write_build_meta(conn, state_hash)
    conn.commit()

    click.echo(f"Cerebrofy: Step 5/6 — Committing index (state_hash: {state_hash[:16]}...)")
    return state_hash


def build_step6_markdown(
    db_path: Path,
    config: CerebrоfyConfig,
    state_hash: str,
    docs_dir: Path,
) -> None:
    """Step 6: Write per-lobe and map Markdown files.

    Opens a FRESH read-only connection to the final (swapped) db_path. The .tmp
    connection is already closed before this function is called.
    """
    click.echo("Cerebrofy: Step 6/6 — Writing Markdown documentation")
    docs_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(db_path)
    try:
        check_schema_version(conn)
        for lobe_name, lobe_path in config.lobes.items():
            write_lobe_md(conn, lobe_name, lobe_path, docs_dir)
        write_map_md(conn, config.lobes, state_hash, docs_dir)
    finally:
        conn.close()


def build_step4_vectors(
    conn: sqlite3.Connection,
    neurons: list[Neuron],
    embedder: Embedder,
) -> None:
    """Step 4: Generate embeddings for all Neurons and upsert into vec_neurons."""
    texts = [build_neuron_text(n) for n in neurons]
    ids = [n.id for n in neurons]
    total = len(neurons)
    batch_size = 256
    for i in range(0, total, batch_size):
        click.echo(
            f"Cerebrofy: Step 4/6 — Generating embeddings ({i} / {total} neurons)"
        )
        texts_batch = texts[i:i + batch_size]
        ids_batch = ids[i:i + batch_size]
        embeddings_batch = embedder.embed(texts_batch)
        upsert_vectors(conn, ids_batch, embeddings_batch)


def build_step2_local_graph(
    conn: sqlite3.Connection,
    parse_results: list[ParseResult],
    name_registry: dict[str, list[Neuron]],
) -> None:
    """Step 2: Resolve intra-file LOCAL_CALL edges and write them to the DB."""
    click.echo("Cerebrofy: Step 2/6 — Building local call graph")
    all_edges: list[Edge] = []
    for pr in parse_results:
        all_edges.extend(resolve_local_edges(pr, name_registry))
    write_edges(conn, all_edges)


def build_step3_cross_module_graph(
    conn: sqlite3.Connection,
    parse_results: list[ParseResult],
    name_registry: dict[str, list[Neuron]],
) -> None:
    """Step 3: Resolve cross-module EXTERNAL_CALL, RUNTIME_BOUNDARY, and IMPORT edges."""
    click.echo("Cerebrofy: Step 3/6 — Resolving cross-module calls")
    all_edges: list[Edge] = []
    for pr in parse_results:
        all_edges.extend(resolve_cross_module_edges(pr, name_registry))
        all_edges.extend(resolve_import_edges(pr, name_registry))
    write_edges(conn, all_edges)


@click.command("build")
def cerebrofy_build() -> None:
    """Build the Cerebrofy index for the current repository."""
    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"

    if not config_path.exists():
        click.echo(
            "Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.", err=True
        )
        sys.exit(1)

    config: CerebrоfyConfig = load_config(config_path)
    ignore_rules = IgnoreRuleSet.from_directory(root)
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    tmp_path = get_tmp_path(db_path)
    lock_path = db_path.parent / "cerebrofy.build.lock"

    # Concurrent build guard
    if lock_path.exists():
        if is_stale(lock_path):
            release(BuildLock(lock_path=lock_path, pid=0))
        else:
            click.echo("Error: A build is already in progress.", err=True)
            sys.exit(1)

    lock = acquire(lock_path)
    cleanup_stale_tmp(tmp_path)

    click.echo("Cerebrofy: Starting build...")
    start = time.monotonic()

    conn: sqlite3.Connection | None = None
    try:
        conn = build_step0_create_db(db_path, config.embedding_model, config.embed_dim)

        parse_results = build_step1_parse(root, config, ignore_rules)

        all_neurons = [n for pr in parse_results for n in pr.neurons]
        write_nodes(conn, all_neurons)

        name_registry = build_name_registry(parse_results)
        build_step2_local_graph(conn, parse_results, name_registry)
        build_step3_cross_module_graph(conn, parse_results, name_registry)

        try:
            embedder = get_embedder(config.embedding_model)
        except (ValueError, Exception) as exc:
            raise RuntimeError(f"Could not initialize embedder: {exc}") from exc
        build_step4_vectors(conn, all_neurons, embedder)

        state_hash = build_step5_commit(conn, root, config, ignore_rules)

        # Close .tmp connection before the atomic swap
        conn.close()
        conn = None

        # Atomic swap: .tmp → .db (only on success)
        os.replace(str(tmp_path), str(db_path))

        docs_dir = root / "docs" / "cerebrofy"
        build_step6_markdown(db_path, config, state_hash, docs_dir)

        elapsed = time.monotonic() - start
        files_count = len(parse_results)
        neurons_count = len(all_neurons)
        click.echo(
            f"Cerebrofy: Build complete. "
            f"Indexed {neurons_count} neurons across {files_count} files in {elapsed:.1f}s."
        )

    except Exception as exc:
        if conn is not None:
            conn.close()
        cleanup_stale_tmp(tmp_path)
        click.echo(f"Error: Build failed: {exc}", err=True)
        sys.exit(1)
    finally:
        release(lock)
