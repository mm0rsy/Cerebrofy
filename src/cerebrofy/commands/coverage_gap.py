"""cerebrofy coverage-gap — rank uncovered neurons by blast_radius × velocity."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import rich_click as click
from rich import box
from rich.console import Console
from rich.table import Table

from cerebrofy.db.connection import check_schema_version

console = Console()

_RISK_COLOR = {"CRITICAL": "red", "HIGH": "dark_orange", "MEDIUM": "yellow", "LOW": "green"}


def _open_db_ro(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' first.")
        sys.exit(1)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _find_repo_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".cerebrofy" / "db" / "cerebrofy.db").exists():
            return parent
    click.echo("Cerebrofy: No index found in current directory or any parent.")
    sys.exit(1)


def _render_text(report: object, top: int) -> None:
    from cerebrofy.analysis.coverage_gap import GapReport
    assert isinstance(report, GapReport)

    source_label = "coverage.xml" if report.coverage_source == "coverage_xml" else "graph topology"
    console.print()
    console.print(
        "[bold]🧠 Cerebrofy — Test Coverage Gap Report[/bold]"
        + (f"  [dim](commit: {report.as_of_commit})[/dim]" if report.as_of_commit else "")
    )
    console.print()

    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("Neurons scanned:", str(report.total_neurons_scanned))
    summary.add_row("Uncovered:", f"[bold red]{report.uncovered_count}[/bold red]")
    summary.add_row("Coverage source:", source_label)
    summary.add_row("Velocity window:", f"{report.velocity_days} days")
    summary.add_row(
        "Showing:",
        f"top {min(top, len(report.neurons))} by gap_score (risk_score × velocity)",
    )
    console.print(summary)
    console.print()

    if not report.neurons:
        console.print("[green]No coverage gaps detected — all active neurons are tested![/green]")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Neuron", style="cyan")
    table.add_column("File", style="dim")
    table.add_column("Callers", justify="right")
    table.add_column(f"Commits/{report.velocity_days}d", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Risk")

    for i, n in enumerate(report.neurons[:top], 1):
        color = _RISK_COLOR.get(n.risk_label, "white")
        table.add_row(
            str(i),
            n.name,
            f"{n.file}:{n.line_start}",
            str(n.caller_count),
            str(n.velocity),
            f"{n.gap_score:.1f}",
            f"[{color}]{n.risk_icon} {n.risk_label}[/{color}]",
        )

    console.print(table)
    console.print()

    critical = [n for n in report.neurons if n.risk_label == "CRITICAL"]
    if critical:
        console.print("[bold red]⚠  Critical gaps — high blast radius, actively changing, untested:[/bold red]")
        for n in critical[:5]:
            console.print(
                f"  • [cyan]{n.name}[/cyan] ({n.file}:{n.line_start})"
                f" — {n.caller_count} callers, {n.velocity} recent commits"
            )
        console.print()


def _render_json(report: object) -> None:
    from cerebrofy.analysis.coverage_gap import GapReport
    assert isinstance(report, GapReport)
    import dataclasses
    out = {
        "as_of_commit": report.as_of_commit,
        "total_neurons_scanned": report.total_neurons_scanned,
        "uncovered_count": report.uncovered_count,
        "coverage_source": report.coverage_source,
        "velocity_days": report.velocity_days,
        "neurons": [dataclasses.asdict(n) for n in report.neurons],
    }
    click.echo(json.dumps(out, indent=2))


@click.command("coverage-gap")
@click.option("--days", default=30, show_default=True,
              help="Velocity window in days (git commits).")
@click.option("--depth", default=2, show_default=True,
              help="BFS caller traversal depth.")
@click.option("--min-blast", default=0.0, show_default=True,
              help="Minimum weighted blast radius (d1 + 0.4×d2) to include a neuron.")
@click.option("--top", default=20, show_default=True,
              help="Number of top gaps to display.")
@click.option("--lobe", default=None, help="Filter analysis to a specific lobe.")
@click.option(
    "--risk", default=None,
    type=click.Choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"], case_sensitive=False),
    help="Filter by risk level.",
)
@click.option("--write-memories", is_flag=True, default=False,
              help="Write warning memories to HIGH/CRITICAL gap neurons.")
@click.option(
    "--output", type=click.Choice(["text", "json"]), default="text", show_default=True,
    help="Output format.",
)
def cerebrofy_coverage_gap(
    days: int, depth: int, min_blast: float, top: int,
    lobe: str | None, risk: str | None,
    write_memories: bool, output: str,
) -> None:
    """Rank uncovered neurons by blast radius × change velocity.

    Surfaces functions that are both widely-called (high blast radius) and
    actively changing (high velocity) but have no test coverage — the highest
    production risk when a bug is introduced.

    Coverage is read from coverage.xml if present (pytest-cov), otherwise
    derived from the call graph (any test file with an edge to the neuron).

    Examples:

    cerebrofy coverage-gap

    cerebrofy coverage-gap --lobe auth

    cerebrofy coverage-gap --days 14 --min-blast 2

    cerebrofy coverage-gap --risk critical --write-memories

    cerebrofy coverage-gap --output json
    """
    from cerebrofy.analysis.coverage_gap import compute_coverage_gap_report

    root = _find_repo_root()
    conn = _open_db_ro(root)
    try:
        try:
            check_schema_version(conn)
        except (ValueError, sqlite3.OperationalError) as exc:
            click.echo(f"Cerebrofy: Schema mismatch — {exc}. Run 'cerebrofy migrate'.")
            sys.exit(1)

        report = compute_coverage_gap_report(
            conn=conn,
            repo_root=root,
            days=days,
            depth=depth,
            min_blast=min_blast,
            top=top,
            lobe_filter=lobe,
            risk_filter=risk,
            write_memories=write_memories,
            cerebrofy_dir=root / ".cerebrofy" if write_memories else None,
        )
    finally:
        conn.close()

    if output == "json":
        _render_json(report)
    else:
        _render_text(report, top)
