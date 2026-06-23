"""cerebrofy impact — pre-change refactor impact predictor."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import rich_click as click
from rich.console import Console
from cerebrofy.analysis.impact import ImpactResult
from cerebrofy.analysis.sequence import SequenceStep
from rich.table import Table
from rich import box

from cerebrofy.db.connection import check_schema_version


_COMPLEXITY_COLOR = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}
_COMPLEXITY_ICON = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}

console = Console()


def _open_db_ro(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' first.")
        sys.exit(1)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _render_text(result: ImpactResult, sequence: list[SequenceStep], show_tests: bool, show_sequence: bool) -> None:
    """Render the impact report as rich terminal output."""
    target = result.target
    icon = _COMPLEXITY_ICON.get(result.complexity_rating, "🟡")
    color = _COMPLEXITY_COLOR.get(result.complexity_rating, "yellow")

    console.print()
    console.print(
        f"[bold]🧠 Cerebrofy — Refactor Impact:[/bold] "
        f"[cyan]{target.name}[/cyan] ({target.file}:{target.line_start})"
    )
    console.print()

    # Summary table
    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    summary.add_column(style="dim")
    summary.add_column()

    depth1 = len(result.callers_by_depth.get(1, []))
    depth2 = len(result.callers_by_depth.get(2, []))
    summary.add_row("Callers (Depth 1):", f"{depth1} function(s)")
    if result.callers_by_depth.get(2):
        summary.add_row("Callers (Depth 2):", f"{depth2} function(s)")
    if show_tests:
        summary.add_row("Tests Covering:", f"{len(result.covering_tests)} test file(s)")
    summary.add_row("Lobes Crossed:", f"{result.lobe_spread} ({', '.join(sorted({target.lobe} | {n.lobe for ns in result.callers_by_depth.values() for n in ns}))})")
    summary.add_row("Estimated LoC:", f"~{result.estimated_loc} lines across affected neurons")
    summary.add_row("Complexity Rating:", f"[{color}]{icon} {result.complexity_rating}[/{color}]")
    console.print(summary)

    # Callers table
    all_callers = [n for ns in result.callers_by_depth.values() for n in ns]
    if all_callers:
        console.print("[bold]Callers (sorted by depth):[/bold]")
        caller_table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        caller_table.add_column("#", style="dim", width=4)
        caller_table.add_column("Neuron")
        caller_table.add_column("File")
        caller_table.add_column("Depth", justify="right")
        idx = 1
        for depth, neurons in sorted(result.callers_by_depth.items()):
            for n in neurons:
                caller_table.add_row(str(idx), n.name, f"{n.file}:{n.line_start}", str(depth))
                idx += 1
        console.print(caller_table)

    # Memory warnings attached to target
    if result.memory_warnings:
        console.print("[bold yellow]⚠️  Memory Warnings:[/bold yellow]")
        for w in result.memory_warnings:
            console.print(f"  • {w}")
        console.print()

    # Runtime boundary warning
    if result.runtime_boundary_callers:
        console.print(
            f"[yellow]⚠️  {len(result.runtime_boundary_callers)} RUNTIME_BOUNDARY caller(s) — "
            "cross process/framework boundary, manual verification required.[/yellow]"
        )
        console.print()

    # Covering tests
    if show_tests and result.covering_tests:
        console.print("[bold]Covering Tests:[/bold]")
        for t in result.covering_tests:
            console.print(f"  • [cyan]{t.file}[/cyan] — {t.name}")
        console.print()

    if show_tests and result.uncovered_callers:
        console.print(f"[yellow]⚠️  {len(result.uncovered_callers)} caller(s) have no detected test coverage.[/yellow]")
        console.print()

    # Refactoring sequence
    if show_sequence and sequence:
        console.print("[bold]Recommended Refactoring Sequence:[/bold]")
        seq_table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        seq_table.add_column("Step", style="dim", width=6)
        seq_table.add_column("Action")
        for step in sequence:
            style = "yellow" if step.is_runtime_boundary else ""
            seq_table.add_row(f"Step {step.step}", f"[{style}]{step.description}[/{style}]" if style else step.description)
        console.print(seq_table)


def _render_json(result: ImpactResult, sequence: list[SequenceStep], show_tests: bool, show_sequence: bool) -> None:
    target = result.target
    out: dict[str, object] = {
        "target": {
            "id": target.id,
            "name": target.name,
            "file": target.file,
            "line_start": target.line_start,
            "lobe": target.lobe,
        },
        "callers_depth1": [
            {"name": n.name, "file": n.file, "line_start": n.line_start}
            for n in result.callers_by_depth.get(1, [])
        ],
        "callers_depth2": [
            {"name": n.name, "file": n.file, "line_start": n.line_start}
            for n in result.callers_by_depth.get(2, [])
        ],
        "lobe_spread": result.lobe_spread,
        "estimated_loc": result.estimated_loc,
        "complexity_rating": result.complexity_rating,
        "runtime_boundary_callers": result.runtime_boundary_callers,
    }
    if show_tests:
        out["covering_tests"] = [
            {"name": t.name, "file": t.file} for t in result.covering_tests
        ]
        out["uncovered_callers"] = result.uncovered_callers
    if show_sequence and sequence:
        out["refactoring_sequence"] = [
            {
                "step": s.step,
                "description": s.description,
                "neuron_ids": s.neuron_ids,
                "is_runtime_boundary": s.is_runtime_boundary,
            }
            for s in sequence
        ]
    click.echo(json.dumps(out, indent=2))


@click.command("impact")
@click.argument("target")
@click.option("--depth", default=2, show_default=True, help="BFS caller traversal depth.")
@click.option("--show-tests/--no-tests", default=True, show_default=True, help="Include covering tests.")
@click.option("--sequence/--no-sequence", "show_sequence", default=True, show_default=True, help="Show refactoring sequence.")
@click.option("--output", type=click.Choice(["text", "json"]), default="text", show_default=True, help="Output format.")
def cerebrofy_impact(
    target: str,
    depth: int,
    show_tests: bool,
    show_sequence: bool,
    output: str,
) -> None:
    """Predict the full impact of refactoring TARGET before touching any code.

    TARGET can be:
    \b
      file::name   e.g. auth/tokens.py::validate_token
      file:line    e.g. auth/tokens.py:42
      name         e.g. validate_token
    """
    from cerebrofy.analysis.impact import compute_impact, resolve_target
    from cerebrofy.analysis.sequence import build_sequence

    root = Path.cwd()
    conn = _open_db_ro(root)

    try:
        try:
            check_schema_version(conn)
        except ValueError as err:
            click.echo(f"Cerebrofy: {err}. Run 'cerebrofy migrate' to update the schema.")
            sys.exit(1)

        neuron = resolve_target(target, conn)
        if neuron is None:
            click.echo(f"Cerebrofy: Neuron '{target}' not found in index. Run 'cerebrofy build' to refresh.")
            sys.exit(1)

        result = compute_impact(neuron, conn, depth=depth, show_tests=show_tests, cerebrofy_dir=root / ".cerebrofy")
        sequence = []
        if show_sequence:
            sequence = build_sequence(
                neuron,
                result.callers_by_depth,
                result.runtime_boundary_callers,
                conn,
            )
    finally:
        conn.close()

    if output == "json":
        _render_json(result, sequence, show_tests, show_sequence)
    else:
        _render_text(result, sequence, show_tests, show_sequence)
