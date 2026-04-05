"""cerebrofy update — partial atomic re-index orchestrator."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import click

from cerebrofy.config.loader import CerebrоfyConfig, load_config
from cerebrofy.db.connection import check_schema_version, open_db
from cerebrofy.db.lock import BuildLock, acquire, is_stale, release
from cerebrofy.db.writer import (
    build_neuron_text,
    compute_state_hash,
    delete_edges_for_files,
    delete_file_hashes,
    delete_nodes_for_files,
    delete_vec_neurons,
    write_build_meta,
    write_edges,
    write_file_hashes,
    write_nodes,
    upsert_vectors,
)
from cerebrofy.embedder import get_embedder
from cerebrofy.graph.edges import Edge
from cerebrofy.graph.resolver import (
    resolve_cross_module_edges,
    resolve_import_edges,
    resolve_local_edges,
)
from cerebrofy.markdown.lobe import write_lobe_md
from cerebrofy.markdown.map import write_map_md
from cerebrofy.parser.engine import parse_file
from cerebrofy.parser.neuron import Neuron, ParseResult
from cerebrofy.update.change_detector import ChangeSet, detect_changes
from cerebrofy.update.scope_resolver import UpdateScope, resolve_scope


@dataclass(frozen=True)
class UpdateResult:
    files_changed: int
    nodes_reindexed: int
    nodes_deleted: int
    new_state_hash: str
    duration_s: float
    model_was_cold: bool


def _check_index_exists(repo_root: Path) -> Path:
    """Return db_path or exit 1 with error if index is missing."""
    db_path = repo_root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo(
            "Error: No index found. Run 'cerebrofy build' first.", err=True
        )
        raise SystemExit(1)
    return db_path


def _compute_new_state_hash(conn: sqlite3.Connection) -> str:
    """Compute state_hash from current file_hashes table using same formula as build."""
    rows = conn.execute("SELECT file, hash FROM file_hashes").fetchall()
    file_hash_map = {file: hash_ for file, hash_ in rows}
    return compute_state_hash(file_hash_map)


def _run_update_transaction(
    conn: sqlite3.Connection,
    scope: UpdateScope,
    new_neurons: list[Neuron],
    new_edges: list[Edge],
    file_hash_map: dict[str, str],
    new_vectors: dict[str, list[float]],
    new_state_hash: str,
) -> tuple[int, int]:
    """Execute partial update inside BEGIN IMMEDIATE. Returns (nodes_reindexed, nodes_deleted).

    new_vectors must be pre-computed BEFORE this call — embedding must NOT happen
    inside the write lock.
    """
    target_files = scope.changed_files | scope.deleted_files
    try:
        conn.execute("BEGIN IMMEDIATE")
        deleted_ids = delete_nodes_for_files(conn, target_files)
        delete_edges_for_files(conn, target_files, deleted_ids)
        delete_vec_neurons(conn, deleted_ids)
        delete_file_hashes(conn, target_files)

        write_nodes(conn, new_neurons)
        write_edges(conn, new_edges)

        # Insert vectors for new neurons (pre-computed outside the lock)
        new_ids_with_embs = [n.id for n in new_neurons if n.id in new_vectors]
        new_embs = [new_vectors[nid] for nid in new_ids_with_embs]
        if new_ids_with_embs:
            upsert_vectors(conn, new_ids_with_embs, new_embs)

        write_file_hashes(conn, file_hash_map)
        write_build_meta(conn, new_state_hash)
        conn.execute("COMMIT")
        return len(new_neurons), len(deleted_ids)
    except Exception:
        conn.rollback()
        raise


def _rewrite_markdown_after_update(
    scope: UpdateScope,
    conn: sqlite3.Connection,
    config: CerebrоfyConfig,
    repo_root: Path,
    state_hash: str,
) -> None:
    """Rewrite affected lobe Markdown files and cerebrofy_map.md."""
    docs_dir = repo_root / "docs" / "cerebrofy"
    docs_dir.mkdir(parents=True, exist_ok=True)
    click.echo("Cerebrofy: Writing Markdown documentation...")
    for lobe_name, lobe_path in config.lobes.items():
        write_lobe_md(conn, lobe_name, lobe_path, docs_dir)
    write_map_md(conn, config.lobes, state_hash, docs_dir)


@click.command("update")
@click.argument("files", nargs=-1, type=click.Path())
def cerebrofy_update(files: tuple[str, ...]) -> None:
    """Partially re-index changed files without a full rebuild."""
    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"

    if not config_path.exists():
        click.echo(
            "Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.",
            err=True,
        )
        sys.exit(1)

    config: CerebrоfyConfig = load_config(config_path)
    db_path = _check_index_exists(root)
    lock_path = db_path.parent / "cerebrofy.build.lock"
    queries_dir = root / ".cerebrofy" / "queries"

    # Concurrent build/update guard
    if lock_path.exists():
        if is_stale(lock_path):
            release(BuildLock(lock_path=lock_path, pid=0))
        else:
            click.echo(
                "Error: A build or update is already in progress.",
                err=True,
            )
            sys.exit(1)

    lock = acquire(lock_path)
    start = time.monotonic()

    try:
        conn = open_db(db_path)
        check_schema_version(conn)

        click.echo("Cerebrofy: Starting update...")

        # Step 1: Detect
        explicit: list[str] | None = list(files) if files else None
        changeset: ChangeSet = detect_changes(root, conn, config, explicit)

        if not changeset.changes:
            click.echo("Cerebrofy: Nothing to update. Index is current.")
            conn.close()
            return

        via = changeset.detected_via
        n_changed = len(changeset.changes)
        if via == "git":
            click.echo(f"Cerebrofy: Detected {n_changed} changed file(s) via git")
        elif via == "hash_comparison":
            click.echo(
                f"Cerebrofy: Detected {n_changed} changed file(s) via hash comparison (no git repository)"
            )
        else:
            click.echo(f"Cerebrofy: Detected {n_changed} changed file(s) via explicit list")

        # Step 2: Scope
        scope: UpdateScope = resolve_scope(changeset, conn)
        click.echo(
            f"Cerebrofy: Update scope: {len(scope.affected_node_ids)} node(s) "
            f"across {len(scope.affected_files)} file(s) (depth-2 BFS)"
        )

        # Step 3: Parse changed files
        click.echo("Cerebrofy: Re-parsing changed files...")
        new_parse_results: list[ParseResult] = []
        for fc in changeset.changes:
            if fc.status == "D":
                continue
            file_path = root / fc.path
            if not file_path.exists():
                continue
            pr = parse_file(file_path, queries_dir, root)
            for w in pr.warnings:
                click.echo(f"Warning: {w}", err=True)
            new_parse_results.append(pr)

        # Step 4: Re-resolve edges for changed files
        click.echo("Cerebrofy: Re-resolving call graph...")
        # Build a name registry from ALL current nodes (existing + new).
        # We pull existing neurons from the DB rather than re-parsing unchanged files.
        from cerebrofy.parser.neuron import Neuron as _Neuron
        existing_rows = conn.execute(
            "SELECT id, name, file, type, line_start, line_end, signature, docstring "
            "FROM nodes"
        ).fetchall()
        existing_neurons: list[Neuron] = [
            _Neuron(
                id=row[0], name=row[1], file=row[2], type=row[3],
                line_start=row[4], line_end=row[5],
                signature=row[6], docstring=row[7],
            )
            for row in existing_rows
        ]
        # Combine: new neurons override existing for changed files
        changed_file_set = scope.changed_files | scope.deleted_files
        kept_neurons = [n for n in existing_neurons if n.file not in changed_file_set]
        new_neurons = [n for pr in new_parse_results for n in pr.neurons]
        all_neurons_for_registry = kept_neurons + new_neurons

        # Build registry from combined neuron set
        registry: dict[str, list[Neuron]] = {}
        for n in all_neurons_for_registry:
            registry.setdefault(n.name, []).append(n)

        new_edges: list[Edge] = []
        for pr in new_parse_results:
            new_edges.extend(resolve_local_edges(pr, registry))
            new_edges.extend(resolve_cross_module_edges(pr, registry))
            new_edges.extend(resolve_import_edges(pr, registry))

        # Step 5: Compute file hashes for changed files
        new_file_hash_map: dict[str, str] = {}
        for fc in changeset.changes:
            if fc.status == "D":
                continue
            file_path = root / fc.path
            if file_path.exists():
                new_file_hash_map[fc.path] = hashlib.sha256(
                    file_path.read_bytes()
                ).hexdigest()

        # Step 6: Embed (BEFORE the write lock)
        total_neurons = len(new_neurons)
        new_vectors: dict[str, list[float]] = {}

        if new_neurons:
            try:
                click.echo("Cerebrofy: Loading embedding model (first invocation may be slow)...")
                embedder = get_embedder(config.embedding_model)
                texts = [build_neuron_text(n) for n in new_neurons]
                click.echo(f"Cerebrofy: Generating embeddings (0 / {total_neurons} neurons)")
                embeddings = embedder.embed(texts)
                click.echo(
                    f"Cerebrofy: Generating embeddings ({total_neurons} / {total_neurons} neurons)"
                )
                for n, emb in zip(new_neurons, embeddings):
                    new_vectors[n.id] = emb
            except Exception as exc:
                click.echo(
                    f"Error: Embedding model unavailable: {exc}. Update aborted.", err=True
                )
                conn.close()
                sys.exit(1)

        # Compute new state_hash (includes existing hashes + updated ones)
        # First update in-memory: merge new hashes into existing
        all_hashes = dict(conn.execute("SELECT file, hash FROM file_hashes").fetchall())
        for f in changed_file_set:
            all_hashes.pop(f, None)
        all_hashes.update(new_file_hash_map)
        new_state_hash = compute_state_hash(all_hashes)

        # Step 7: Atomic transaction
        nodes_reindexed, nodes_deleted = _run_update_transaction(
            conn, scope, new_neurons, new_edges,
            new_file_hash_map, new_vectors, new_state_hash,
        )

        # Step 8: Rewrite Markdown (post-commit)
        _rewrite_markdown_after_update(scope, conn, config, root, new_state_hash)
        conn.close()

        elapsed = time.monotonic() - start

        # Upgrade pre-push hook to hard-block once update is verified fast enough (FR-003/FR-014).
        # upgrade_hook() is idempotent — no-op if already version 2.
        if elapsed < 2.0:
            from cerebrofy.hooks.installer import upgrade_hook
            pre_push = root / ".git" / "hooks" / "pre-push"
            upgrade_hook(pre_push)

        click.echo(
            f"Cerebrofy: Update complete. Re-indexed {nodes_reindexed} neurons "
            f"in {elapsed:.1f}s. New state_hash: {new_state_hash[:16]}..."
        )

    except SystemExit:
        raise
    except Exception as exc:
        click.echo(f"Error: Update failed: {exc}", err=True)
        sys.exit(1)
    finally:
        release(lock)
