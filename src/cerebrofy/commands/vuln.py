"""cerebrofy vuln — vulnerability blast radius scanner."""

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
from cerebrofy.security.vuln_scanner import VulnResult


console = Console()


def _open_db_ro(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' first.")
        sys.exit(1)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _render_text(result: VulnResult) -> None:
    console.print()
    pkg_label = result.package
    if result.function_pattern:
        pkg_label += f" ({result.function_pattern})"
    console.print(f"[bold]🧠 Cerebrofy — Vulnerability Blast Radius:[/bold] [cyan]{pkg_label}[/cyan]")
    if result.pinned_version:
        console.print(f"  [dim]Pinned: {result.pinned_version}[/dim]")
    console.print()

    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("Direct Callers:", str(len(result.direct_callers)))
    summary.add_row("Upstream Callers:", str(result.upstream_count))
    summary.add_row("Critical Exposure:", str(len(result.critical_exposure)))
    summary.add_row("Low/Test Exposure:", str(len(result.low_exposure)))
    if result.memories_written:
        summary.add_row("Memories Written:", str(result.memories_written))
    console.print(summary)

    if result.critical_exposure:
        console.print("[bold red]🔴 CRITICAL EXPOSURE (external input reaches vulnerable call):[/bold red]")
        crit_table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        crit_table.add_column("Entry Point", style="red")
        crit_table.add_column("Call Chain")
        crit_table.add_column("Score", justify="right")
        for path in sorted(result.critical_exposure, key=lambda p: -p.exposure_score):
            chain = " → ".join(path.call_chain)
            crit_table.add_row(
                f"{path.entry_point_name} ({path.entry_point_file})",
                chain,
                f"{path.exposure_score:.1f}",
            )
        console.print(crit_table)

    if result.low_exposure:
        console.print("[bold]🟡 LOW EXPOSURE (no direct external input path):[/bold]")
        for caller in result.low_exposure:
            label = "[dim](test)[/dim]" if caller.is_test else ""
            console.print(f"  • [dim]{caller.file}[/dim]::{caller.name} {label}")
        console.print()

    if result.remediation_sequence:
        console.print("[bold]Remediation Sequence:[/bold]")
        rem_table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        rem_table.add_column("Step", style="dim", width=6)
        rem_table.add_column("Action")
        for step in result.remediation_sequence:
            rem_table.add_row(f"Step {step['step']}", step["description"])
        console.print(rem_table)


def _render_json(result: VulnResult) -> None:
    out = {
        "package": result.package,
        "function_pattern": result.function_pattern,
        "pinned_version": result.pinned_version,
        "direct_callers": [
            {
                "name": c.name,
                "file": c.file,
                "line_start": c.line_start,
                "call_target": c.call_target,
                "is_trust_boundary": c.is_trust_boundary,
                "is_test": c.is_test,
            }
            for c in result.direct_callers
        ],
        "critical_exposure": [
            {
                "entry_point": f"{p.entry_point_file}::{p.entry_point_name}",
                "call_chain": p.call_chain,
                "exposure_score": p.exposure_score,
            }
            for p in result.critical_exposure
        ],
        "low_exposure": [
            {"name": c.name, "file": c.file, "is_test": c.is_test}
            for c in result.low_exposure
        ],
        "remediation_sequence": result.remediation_sequence,
        "memories_written": result.memories_written,
    }
    click.echo(json.dumps(out, indent=2))


@click.command("vuln")
@click.option("--package", required=True, help="Package name to scan (e.g. requests).")
@click.option("--function", "function_pattern", default=None, help="Specific function to trace (e.g. requests.get).")
@click.option("--depth", default=2, show_default=True, help="Upstream BFS depth.")
@click.option("--write-memories", is_flag=True, default=False, help="Write warning memories to affected neurons.")
@click.option("--output", type=click.Choice(["text", "json"]), default="text", show_default=True, help="Output format.")
def cerebrofy_vuln(
    package: str,
    function_pattern: str | None,
    depth: int,
    write_memories: bool,
    output: str,
) -> None:
    """Map which of YOUR functions are exposed to a vulnerable package.

    \b
    Examples:
      cerebrofy vuln --package requests
      cerebrofy vuln --package requests --function requests.get
      cerebrofy vuln --package requests --write-memories
    """
    from cerebrofy.security.vuln_scanner import compute_vuln_blast_radius

    root = Path.cwd()
    conn = _open_db_ro(root)

    try:
        try:
            check_schema_version(conn)
        except (ValueError, sqlite3.OperationalError) as err:
            click.echo(f"Cerebrofy: {err}. Run 'cerebrofy migrate' to update the schema.")
            sys.exit(1)

        result = compute_vuln_blast_radius(
            package=package,
            function_pattern=function_pattern,
            conn=conn,
            depth=depth,
            cerebrofy_dir=root / ".cerebrofy" if write_memories else None,
            write_memories=write_memories,
            root=root,
        )
    finally:
        conn.close()

    if not result.direct_callers:
        click.echo(f"Cerebrofy: Package '{package}' not found in the call graph. Not used or index needs rebuild.")
        sys.exit(0)

    if output == "json":
        _render_json(result)
    else:
        _render_text(result)
