"""cerebrofy build — 6-step atomic pipeline orchestrator."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import click

from cerebrofy.config.loader import load_config
from cerebrofy.db.connection import open_db
from cerebrofy.db.schema import create_schema
from cerebrofy.db.writer import (
    compute_file_hash,
    compute_state_hash,
    insert_meta,
    write_build_meta,
    write_file_hashes,
    write_nodes,
)
from cerebrofy.ignore.ruleset import IgnoreRuleSet
from cerebrofy.parser.engine import parse_directory


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
    """Step 0: Create (or truncate) the database, apply schema, write initial meta rows.

    In US1 writes directly to db_path. US5 updates this to write to get_tmp_path(db_path).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Remove stale db so CREATE TABLE succeeds on a fresh connection.
    # US5 replaces this pattern with atomic .tmp → .db swap.
    db_path.unlink(missing_ok=True)
    conn = open_db(db_path)
    create_schema(conn, embed_dim)
    insert_meta(conn, embed_model, embed_dim)
    return conn


def build_step1_parse(
    root: Path,
    config: object,
    ignore_rules: IgnoreRuleSet,
) -> list:  # list[ParseResult]
    """Step 1: Parse all tracked source files and return ParseResult list."""
    from cerebrofy.config.loader import CerebrоfyConfig
    cfg: CerebrоfyConfig = config  # type: ignore[assignment]

    # Pre-scan to know N before the batch call (two-print contract from spec)
    tracked_files = [
        f for f in sorted(root.rglob("*"))
        if f.is_file()
        and not ignore_rules.matches(str(f.relative_to(root)).replace("\\", "/"))
        and f.suffix.lower() in cfg.tracked_extensions
    ]
    n = len(tracked_files)

    queries_dir = root / ".cerebrofy" / "queries"
    click.echo(f"Cerebrofy: Step 1/6 — Parsing source files (0 / {n} files)")
    parse_results = parse_directory(root, cfg, ignore_rules, queries_dir=queries_dir)
    click.echo(f"Cerebrofy: Step 1/6 — Parsing source files ({n} / {n} files)")

    for pr in parse_results:
        for warning in pr.warnings:
            click.echo(f"Warning: {warning}", err=True)

    return parse_results


def build_step6_commit(
    conn: sqlite3.Connection,
    root: Path,
    config: object,
    ignore_rules: IgnoreRuleSet,
) -> str:
    """Step 6: Compute file hashes, write state_hash + last_build, commit."""
    from cerebrofy.config.loader import CerebrоfyConfig
    cfg: CerebrоfyConfig = config  # type: ignore[assignment]

    file_hash_map: dict[str, str] = {}
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = str(file_path.relative_to(root)).replace("\\", "/")
        if ignore_rules.matches(rel_path):
            continue
        if file_path.suffix.lower() not in cfg.tracked_extensions:
            continue
        file_hash_map[rel_path] = compute_file_hash(file_path)

    write_file_hashes(conn, file_hash_map)
    state_hash = compute_state_hash(file_hash_map)
    write_build_meta(conn, state_hash)
    conn.commit()

    click.echo(f"Cerebrofy: Step 6/6 — Committing index (state_hash: {state_hash[:16]}...)")
    return state_hash


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

    config = load_config(config_path)
    ignore_rules = IgnoreRuleSet.from_directory(root)
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    click.echo("Cerebrofy: Starting build...")
    start = time.monotonic()

    conn = build_step0_create_db(db_path, config.embedding_model, config.embed_dim)

    parse_results = build_step1_parse(root, config, ignore_rules)

    all_neurons = [n for pr in parse_results for n in pr.neurons]
    write_nodes(conn, all_neurons)

    state_hash = build_step6_commit(conn, root, config, ignore_rules)

    elapsed = time.monotonic() - start
    files_count = len(parse_results)
    neurons_count = len(all_neurons)
    click.echo(
        f"Cerebrofy: Build complete. "
        f"Indexed {neurons_count} neurons across {files_count} files in {elapsed:.1f}s."
    )
