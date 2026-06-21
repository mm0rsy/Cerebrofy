"""cerebrofy epistemic — epistemic confidence and staleness state command."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import rich_click as click

from cerebrofy.config.loader import load_config
from cerebrofy.db.connection import open_db


@click.command("epistemic")
@click.option(
    "--json", "as_json",
    is_flag=True, default=False,
    help="Output machine-readable JSON for agent consumption.",
)
def cerebrofy_epistemic(as_json: bool) -> None:
    """Show epistemic confidence score and staleness warnings for the current index."""
    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    if not config_path.exists():
        click.echo(
            "Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.", err=True
        )
        sys.exit(1)

    if not db_path.exists():
        click.echo("Error: No index found. Run 'cerebrofy build' first.", err=True)
        sys.exit(1)

    config = load_config(config_path)
    conn = open_db(db_path)

    try:
        from cerebrofy.epistemic.state import compute_epistemic_state

        state = compute_epistemic_state(conn, config.tracked_extensions, root)
    finally:
        conn.close()

    if as_json:
        click.echo(json.dumps(state.to_dict(), indent=2))
        return

    pct = int(state.overall_confidence * 100)
    click.echo(f"\n🧠 Cerebrofy — Epistemic Confidence: {pct}%\n")
    click.echo(f"  Graph age:            {state.graph_age_hours:.1f}h")
    click.echo(f"  Neurons changed:      {state.neurons_changed_since_build}")
    click.echo(f"  Missing test paths:   {state.missing_test_paths}")
    click.echo(f"  Dynamic dispatch:     {state.dynamic_dispatch_count}")
    click.echo(f"  Unindexed languages:  {', '.join(state.unindexed_languages) or 'none'}")

    if state.caveats:
        click.echo("\n  Caveats:")
        for c in state.caveats:
            click.echo(f"    ⚠️  {c}")

    click.echo(f"\n  Recommendation: {state.recommendation}\n")
