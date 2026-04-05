"""cerebrofy validate — tiered drift classification command."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import click

from cerebrofy.db.connection import check_schema_version
from cerebrofy.validate.drift_classifier import DriftRecord, classify_drift


@dataclass(frozen=True)
class ValidationResult:
    exit_code: int
    drift_type: str
    structural_records: tuple[DriftRecord, ...]
    minor_records: tuple[DriftRecord, ...]


@click.command("validate")
@click.option("--hook", default=None, help="Hook name (reserved for future use).")
def cerebrofy_validate(hook: str | None) -> None:
    """Classify drift between index and current source. Exits 1 on structural drift."""
    root = Path.cwd()
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    config_path = root / ".cerebrofy" / "config.yaml"

    if not db_path.exists():
        click.echo(
            "Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' to initialize."
        )
        sys.exit(0)

    from cerebrofy.config.loader import CerebrоfyConfig, load_config
    from cerebrofy.ignore.ruleset import IgnoreRuleSet

    config: CerebrоfyConfig = load_config(config_path)
    ignore_rules = IgnoreRuleSet.from_directory(root)

    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    try:
        # Invariant: verify schema version before any read (CLAUDE.md invariant).
        try:
            check_schema_version(conn)
        except ValueError as schema_err:
            click.echo(
                f"Cerebrofy: {schema_err}. Run 'cerebrofy migrate' to update the schema."
            )
            sys.exit(0)  # Schema mismatch is WARN-only; never blocks

        # Collect all tracked files currently on disk
        tracked_files: list[str] = []
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(root)).replace("\\", "/")
            if ignore_rules.matches(rel):
                continue
            if file_path.suffix.lower() in config.tracked_extensions:
                tracked_files.append(rel)

        # Also include indexed files that no longer exist on disk — deleting a
        # tracked file removes all its Neurons, which is structural drift.
        indexed_files = {
            row[0] for row in conn.execute("SELECT file FROM file_hashes").fetchall()
        }
        deleted_indexed = list(indexed_files - set(tracked_files))
        all_files_to_check = tracked_files + deleted_indexed

        records = classify_drift(all_files_to_check, conn, config, root)

    finally:
        conn.close()

    structural = [r for r in records if r.drift_type == "structural"]
    minor = [r for r in records if r.drift_type == "minor"]

    if structural:
        click.echo("Cerebrofy: STRUCTURAL DRIFT DETECTED — push blocked.")
        click.echo("Cerebrofy: The following code units are out of sync with the index:")
        click.echo("")
        for record in structural:
            click.echo(record.drift_detail)
        click.echo("")
        click.echo("Run 'cerebrofy update' to resync, then retry your push.")
        sys.exit(1)

    if minor:
        n = len(minor)
        click.echo(
            f"Cerebrofy: Minor drift detected in {n} file(s) — whitespace/comments only."
        )
        click.echo("Cerebrofy: Suggestion: run 'cerebrofy update' to keep the index current.")
        sys.exit(0)

    click.echo("Cerebrofy: Index is clean.")
    sys.exit(0)
