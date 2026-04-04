"""cerebrofy validate — tiered drift classification command."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import click

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
        # Collect all tracked files as potential candidates
        tracked_files: list[str] = []
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(root)).replace("\\", "/")
            if ignore_rules.matches(rel):
                continue
            if file_path.suffix.lower() in config.tracked_extensions:
                tracked_files.append(rel)

        records = classify_drift(tracked_files, conn, config, root)

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

    click.echo("Cerebrofy: Index is current. No drift detected.")
    sys.exit(0)
