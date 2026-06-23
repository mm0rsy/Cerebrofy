"""cerebrofy onboard — generate an ONBOARDING guide from the cerebrofy index."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import rich_click as click
from rich.console import Console

from cerebrofy.config.loader import load_config
from cerebrofy.db.connection import check_schema_version

console = Console()


def _open_db_ro(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' first.")
        sys.exit(1)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


@click.command("onboard")
@click.option("--name", default=None, help="Your name for a personalised greeting.")
@click.option(
    "--focus", "focus_lobe", default=None, metavar="LOBE",
    help="Restrict the guide to this lobe and its immediate neighbours.",
)
@click.option(
    "--depth",
    type=click.Choice(["junior", "senior"]),
    default="junior",
    show_default=True,
    help="Calibration hint embedded in the guide for AI agents.",
)
@click.option(
    "--format", "fmt",
    type=click.Choice(["markdown", "html"]),
    default="markdown",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output", "output_path", default=None, metavar="PATH",
    help="Write to this path instead of .cerebrofy/ONBOARDING.{md,html}.",
)
def cerebrofy_onboard(
    name: str | None,
    focus_lobe: str | None,
    depth: str,
    fmt: str,
    output_path: str | None,
) -> None:
    """Generate an ONBOARDING guide from the cerebrofy index.

    \b
    Produces a reading-order map, entry points, complexity hotspots, and safe
    zones derived from the call graph. Pass the result to an AI agent — the
    --depth flag is a calibration hint for how to explain it.

    \b
    Examples:
      cerebrofy onboard
      cerebrofy onboard --name Alice --depth junior
      cerebrofy onboard --focus auth --format html
    """
    root = Path.cwd()
    cerebrofy_dir = root / ".cerebrofy"

    config_path = cerebrofy_dir / "config.yaml"
    if not config_path.exists():
        click.echo("Cerebrofy: No .cerebrofy/config.yaml found. Run 'cerebrofy init' first.")
        sys.exit(1)

    config = load_config(config_path)
    conn = _open_db_ro(root)
    try:
        try:
            check_schema_version(conn)
        except ValueError as err:
            click.echo(f"Cerebrofy: {err}. Run 'cerebrofy migrate'.")
            sys.exit(1)

        from cerebrofy.onboard.planner import build_plan
        plan = build_plan(
            conn=conn,
            lobes=config.lobes,
            cerebrofy_dir=cerebrofy_dir,
            repo_name=root.name,
            depth=depth,
            name=name,
            focus_lobe=focus_lobe,
        )
    finally:
        conn.close()

    if fmt == "html":
        from cerebrofy.onboard.html_renderer import render_html
        content = render_html(plan)
        ext = "html"
    else:
        from cerebrofy.onboard.renderer import render_markdown
        content = render_markdown(plan)
        ext = "md"

    out = Path(output_path) if output_path else cerebrofy_dir / f"ONBOARDING.{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")

    try:
        display_path = out.relative_to(root)
    except ValueError:
        display_path = out

    console.print(f"[bold green]✓[/bold green] Written to [bold]{display_path}[/bold]")
    console.print(
        f"  {len(plan.lobe_reading_order)} modules · "
        f"{len(plan.entry_points)} entry points · "
        f"{len(plan.hotspots)} hotspots · "
        f"{len(plan.safe_zones)} safe zones"
    )
