"""cerebrofy silo — knowledge silo detector: git blame × call graph = bus factor risk."""

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
    from cerebrofy.analysis.silo_detector import SiloReport
    assert isinstance(report, SiloReport)

    console.print()
    console.print(
        "[bold]🧠 Cerebrofy — Knowledge Silo Report[/bold]"
        + (f"  [dim](commit: {report.as_of_commit})[/dim]" if report.as_of_commit else "")
    )
    console.print()

    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("Neurons scanned:", str(report.total_neurons_scanned))
    summary.add_row("Single-author silos:", f"[bold red]{report.silos_detected}[/bold red]")
    summary.add_row(
        "Showing:",
        f"top {min(top, len(report.neurons))} by silo score (callers ÷ unique authors)",
    )
    console.print(summary)
    console.print()

    if not report.neurons:
        console.print("[green]No silos detected — well-distributed authorship![/green]")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Neuron", style="cyan")
    table.add_column("File", style="dim")
    table.add_column("Authors", justify="right")
    table.add_column("Primary owner", style="dim")
    table.add_column("Own%", justify="right")
    table.add_column("Callers", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Risk")

    for i, n in enumerate(report.neurons[:top], 1):
        color = _RISK_COLOR.get(n.risk_label, "white")
        table.add_row(
            str(i),
            n.name,
            f"{n.file}:{n.line_start}",
            str(n.unique_authors),
            n.primary_author,
            f"{n.primary_author_pct:.0%}",
            str(n.caller_count),
            f"{n.silo_score:.1f}",
            f"[{color}]{n.risk_icon} {n.risk_label}[/{color}]",
        )

    console.print(table)
    console.print()

    critical = [n for n in report.neurons if n.risk_label == "CRITICAL"]
    if critical:
        console.print("[bold red]⚠  Critical silos — single author, high blast radius:[/bold red]")
        for n in critical[:5]:
            console.print(f"  • [cyan]{n.name}[/cyan] ({n.file}:{n.line_start})"
                          f" — owner: {n.primary_author}")
        console.print()


def _render_json(report: object) -> None:
    from cerebrofy.analysis.silo_detector import SiloReport
    assert isinstance(report, SiloReport)
    import dataclasses
    out = {
        "as_of_commit": report.as_of_commit,
        "total_neurons_scanned": report.total_neurons_scanned,
        "silos_detected": report.silos_detected,
        "neurons": [dataclasses.asdict(n) for n in report.neurons],
    }
    click.echo(json.dumps(out, indent=2))


@click.command("silo")
@click.option("--depth", default=2, show_default=True, help="BFS caller traversal depth.")
@click.option("--min-callers", default=1, show_default=True,
              help="Minimum caller count to include a neuron.")
@click.option("--top", default=20, show_default=True, help="Number of top silos to display.")
@click.option(
    "--output", type=click.Choice(["text", "json"]), default="text", show_default=True,
    help="Output format.",
)
def cerebrofy_silo(depth: int, min_callers: int, top: int, output: str) -> None:
    """Identify knowledge silos — functions with high blast radius owned by few contributors.

    Overlays git blame authorship on the call graph to surface bus factor risk:
    a function called by many but understood by one is a single point of failure.

    Examples:

    cerebrofy silo

    cerebrofy silo --top 10 --min-callers 3

    cerebrofy silo --output json
    """
    from cerebrofy.analysis.silo_detector import compute_silo_report

    root = _find_repo_root()
    conn = _open_db_ro(root)
    try:
        try:
            check_schema_version(conn)
        except (ValueError, sqlite3.OperationalError) as exc:
            click.echo(f"Cerebrofy: Schema mismatch — {exc}. Run 'cerebrofy migrate'.")
            sys.exit(1)

        report = compute_silo_report(
            conn=conn,
            repo_root=root,
            depth=depth,
            min_callers=min_callers,
            top=top,
        )
    finally:
        conn.close()

    if output == "json":
        _render_json(report)
    else:
        _render_text(report, top)
