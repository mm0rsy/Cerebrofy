"""cerebrofy migrate — sequential schema migration runner."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import click


@dataclass(frozen=True)
class MigrationStep:
    from_version: int
    to_version: int
    script_path: Path


@dataclass(frozen=True)
class MigrationPlan:
    current_version: int
    target_version: int
    steps: tuple[MigrationStep, ...]
    is_already_current: bool
    has_gap: bool


def _load_migration_plan(
    conn: object,
    migrations_dir: Path,
    target_version: int,
) -> MigrationPlan:
    """Read schema_version, scan migrations dir, build ordered MigrationPlan."""
    import sqlite3

    c: sqlite3.Connection = conn  # type: ignore[assignment]
    row = c.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    current_version = int(row[0]) if row else 0

    if current_version >= target_version:
        return MigrationPlan(
            current_version=current_version,
            target_version=target_version,
            steps=(),
            is_already_current=True,
            has_gap=False,
        )

    steps: list[MigrationStep] = []
    has_gap = False
    for v in range(current_version, target_version):
        script_path = migrations_dir / f"v{v}_to_v{v + 1}.py"
        if not script_path.exists():
            has_gap = True
            break
        steps.append(MigrationStep(from_version=v, to_version=v + 1, script_path=script_path))

    return MigrationPlan(
        current_version=current_version,
        target_version=target_version,
        steps=tuple(steps),
        is_already_current=False,
        has_gap=has_gap,
    )


def _apply_migration_step(conn: object, step: MigrationStep) -> None:
    """Load and execute a migration script's upgrade() function atomically."""
    import importlib.util
    import sqlite3

    c: sqlite3.Connection = conn  # type: ignore[assignment]
    spec = importlib.util.spec_from_file_location("migration_script", step.script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load migration script: {step.script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    try:
        c.execute("BEGIN IMMEDIATE")
        module.upgrade(c)
        c.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(step.to_version),),
        )
        c.execute("COMMIT")
    except Exception:
        c.rollback()
        raise


@click.command("migrate")
@click.option(
    "--target",
    default=1,
    type=int,
    show_default=True,
    help="Target schema version.",
)
def cerebrofy_migrate(target: int) -> None:
    """Apply sequential schema migrations up to the target version."""
    import sqlite3

    root = Path.cwd()
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    if not db_path.exists():
        click.echo(
            "Error: No index found. Run 'cerebrofy build' first.", err=True
        )
        sys.exit(1)

    migrations_dir = root / ".cerebrofy" / "scripts" / "migrations"
    conn = sqlite3.connect(str(db_path))

    try:
        plan = _load_migration_plan(conn, migrations_dir, target)

        if plan.is_already_current:
            click.echo(f"Schema already at version {plan.current_version}")
            sys.exit(0)

        if plan.has_gap:
            click.echo(
                f"Error: Missing migration script(s) between version "
                f"{plan.current_version} and {target}.",
                err=True,
            )
            sys.exit(1)

        for step in plan.steps:
            click.echo(f"Cerebrofy: Migrating v{step.from_version} → v{step.to_version}...")
            _apply_migration_step(conn, step)
            click.echo(f"Cerebrofy: Migration to v{step.to_version} complete.")

        click.echo(f"Cerebrofy: Schema at version {target}.")
    finally:
        conn.close()
