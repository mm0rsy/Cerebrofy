"""cerebrofy blast-radius — PR blast radius reporter."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.table import Table
from rich import box

from cerebrofy.db.connection import check_schema_version
from cerebrofy.analysis.blast_radius import (
    BlastRadiusReport,
    NeuronBlastRadius,
    compute_blast_radius_report,
    format_pr_comment,
    neuron_for_target,
    neurons_for_changed_files,
)

console = Console()


def _open_db_ro(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' first.")
        sys.exit(1)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _changed_files_from_git(base: str, head: str, root: Path) -> list[str]:
    """Return list of changed file paths between base and head."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base, head],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"Cerebrofy: git diff failed — {result.stderr.strip()}")
        sys.exit(1)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _render_text(report: BlastRadiusReport) -> None:
    console.print()
    console.print("[bold]🧠 Cerebrofy — Blast Radius Report[/bold]")
    console.print()

    t = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    t.add_column("Function")
    t.add_column("File")
    t.add_column("Callers (d1+d2)", justify="right")
    t.add_column("Tests", justify="right")
    t.add_column("Risk")

    for nbr in report.changed_neurons:
        total = len(nbr.callers_depth1) + len(nbr.callers_depth2)
        color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}.get(nbr.risk_label, "white")
        t.add_row(
            nbr.neuron.name,
            f"{nbr.neuron.file}:{nbr.neuron.line_start}",
            str(total),
            str(len(nbr.covering_tests)),
            f"[{color}]{nbr.risk_icon} {nbr.risk_label}[/{color}]",
        )

    console.print(t)

    for nbr in report.changed_neurons:
        if not nbr.callers_depth1 and not nbr.callers_depth2:
            continue
        console.print(f"[bold]{nbr.neuron.name}[/bold] — caller tree")
        if nbr.callers_depth1:
            console.print(f"  Depth 1: {', '.join(n.name for n in nbr.callers_depth1)}")
        if nbr.callers_depth2:
            console.print(f"  Depth 2: {', '.join(n.name for n in nbr.callers_depth2)}")
        if nbr.runtime_boundary_callers:
            console.print(f"  [yellow]⚠️  RUNTIME_BOUNDARY: {', '.join(nbr.runtime_boundary_callers)}[/yellow]")
        if nbr.uncovered_callers:
            names = [c.split("::")[-1] for c in nbr.uncovered_callers if not c.startswith("external::")]
            if names:
                console.print(f"  [yellow]Uncovered: {', '.join(names[:5])}[/yellow]")
        console.print()

    console.print(
        f"Total affected: [bold]{report.total_affected}[/bold] | "
        f"Highest risk: [bold]{report.highest_risk_label}[/bold]"
    )


def _render_json(report: BlastRadiusReport) -> None:
    out: dict[str, object] = {
        "total_affected": report.total_affected,
        "highest_risk": report.highest_risk_label,
        "changed_neurons": [
            {
                "name": nbr.neuron.name,
                "file": nbr.neuron.file,
                "line_start": nbr.neuron.line_start,
                "callers_depth1": [{"name": n.name, "file": n.file} for n in nbr.callers_depth1],
                "callers_depth2": [{"name": n.name, "file": n.file} for n in nbr.callers_depth2],
                "covering_tests": [{"name": n.name, "file": n.file} for n in nbr.covering_tests],
                "uncovered_callers": nbr.uncovered_callers,
                "runtime_boundary_callers": nbr.runtime_boundary_callers,
                "lobe_spread": nbr.lobe_spread,
                "risk_score": round(nbr.risk_score, 3),
                "risk_label": nbr.risk_label,
            }
            for nbr in report.changed_neurons
        ],
    }
    click.echo(json.dumps(out, indent=2))


@click.command("blast-radius")
@click.argument("target", required=False, default=None)
@click.option("--base", default=None, help="Base git ref for diff (e.g. main, HEAD~1).")
@click.option("--head", default="HEAD", show_default=True, help="Head git ref for diff.")
@click.option("--pr", "pr_number", default=None, type=int, help="GitHub PR number (fetches diff via gh CLI).")
@click.option("--depth", default=2, show_default=True, help="BFS traversal depth.")
@click.option("--output", type=click.Choice(["text", "json", "markdown"]), default="text", show_default=True, help="Output format.")
@click.option("--post-comment", is_flag=True, default=False, help="Post result as a GitHub PR comment (requires --pr and gh CLI).")
@click.option("--repo", default=None, help="GitHub repo (owner/name) for --post-comment.")
def cerebrofy_blast_radius(
    target: str | None,
    base: str | None,
    head: str,
    pr_number: int | None,
    depth: int,
    output: str,
    post_comment: bool,
    repo: str | None,
) -> None:
    """Show every caller affected by a change — before merging.

    \b
    Usage modes:
      cerebrofy blast-radius --base main --head HEAD   # diff two refs
      cerebrofy blast-radius --pr 142                  # fetch PR diff via gh CLI
      cerebrofy blast-radius auth/tokens.py::validate_token  # single neuron
    """
    from cerebrofy.ci.github_commenter import (
        get_pr_diff,
        parse_changed_files_from_diff,
    )

    root = Path.cwd()
    conn = _open_db_ro(root)

    try:
        try:
            check_schema_version(conn)
        except ValueError as err:
            click.echo(f"Cerebrofy: {err}. Run 'cerebrofy migrate'.")
            sys.exit(1)

        neurons = []

        if target:
            neuron = neuron_for_target(target, conn)
            if neuron is None:
                click.echo(f"Cerebrofy: Neuron '{target}' not found. Run 'cerebrofy build' first.")
                sys.exit(1)
            neurons = [neuron]

        elif pr_number is not None:
            ok, diff_or_err = get_pr_diff(pr_number, repo=repo)
            if not ok:
                click.echo(f"Cerebrofy: Could not fetch PR diff — {diff_or_err}")
                sys.exit(1)
            changed_files = parse_changed_files_from_diff(diff_or_err)
            neurons = neurons_for_changed_files(changed_files, conn)

        elif base is not None:
            changed_files = _changed_files_from_git(base, head, root)
            neurons = neurons_for_changed_files(changed_files, conn)

        else:
            click.echo(
                "Cerebrofy: Provide TARGET, --base <ref>, or --pr <number>.\n"
                "Run 'cerebrofy blast-radius --help' for usage."
            )
            sys.exit(1)

        if not neurons:
            click.echo("Cerebrofy: No indexed neurons found in changed files.")
            sys.exit(0)

        report = compute_blast_radius_report(neurons, conn, depth=depth)

    finally:
        conn.close()

    if output == "json":
        _render_json(report)
    elif output == "markdown":
        click.echo(format_pr_comment(report))
    else:
        _render_text(report)

    if post_comment:
        if pr_number is None:
            click.echo("Cerebrofy: --post-comment requires --pr <number>.")
            sys.exit(1)
        from cerebrofy.ci.github_commenter import post_pr_comment
        md = format_pr_comment(report)
        ok, msg = post_pr_comment(pr_number, md, repo=repo)
        if ok:
            click.echo(f"Cerebrofy: Comment posted to PR #{pr_number}.")
        else:
            click.echo(f"Cerebrofy: Failed to post comment — {msg}")
            sys.exit(1)
