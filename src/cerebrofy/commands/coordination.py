"""Multi-agent coordination CLI (Idea #25).

Top-level commands (``cerebrofy who|claim|release|conflicts|resolve``) let
several agents — and humans — work on one codebase without silently undoing each
other.  A ``cerebrofy coordination`` group exposes the same subcommands as an
alias.

Registry state lives in the local index database
(``.cerebrofy/db/cerebrofy.db``), so claims are visible to every Cerebrofy
process on this machine.  Rebuilding the index recreates that database, which
means coordination state is ephemeral by design.

Agent identity defaults to ``$CEREBROFY_AGENT_ID`` and falls back to
``human-<username>``; pass ``--agent-id`` to override.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path
from typing import NoReturn

import rich_click as click
from rich import box
from rich.console import Console
from rich.table import Table

from cerebrofy.coordination.conflict_detector import ConflictDetector
from cerebrofy.coordination.constants import (
    DEFAULT_TTL_MINUTES,
    MAX_TTL_MINUTES,
)
from cerebrofy.coordination.metrics import get_metrics, get_persistent_metrics
from cerebrofy.coordination.neurons import expand_neurons
from cerebrofy.coordination.registry import ActiveAgentRegistry
from cerebrofy.coordination.resolver import ConflictResolver
from cerebrofy.errors import (
    CONFIG_ERROR,
    NEURON_ALREADY_CLAIMED,
    CerebrofyError,
)

console = Console()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_root() -> Path:
    """Resolve the repo root via the shared finder; exit the CLI on failure."""
    from cerebrofy.utils.paths import InvalidRepoRootError, require_repo_root

    try:
        return require_repo_root()
    except FileNotFoundError:
        click.echo("Error: Not initialized. Run 'cerebrofy init' first.", err=True)
        sys.exit(1)
    except InvalidRepoRootError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


def _index_path(root: Path) -> Path:
    return root / ".cerebrofy" / "db" / "cerebrofy.db"


def _memories_path(root: Path) -> Path:
    return root / ".cerebrofy" / "db" / "memories.db"


def _open_registry(root: Path) -> ActiveAgentRegistry:
    """Open the registry against the local index, exiting when it is absent."""
    db_path = _index_path(root)
    if not db_path.exists():
        click.echo(
            "Error: Index not found. Run 'cerebrofy build' first.", err=True
        )
        sys.exit(1)
    return ActiveAgentRegistry(db_path)


def _agent_id(explicit: str | None) -> str:
    """Resolve the acting agent id: flag > env > ``human-<username>``."""
    if explicit:
        return explicit
    from_env = os.environ.get("CEREBROFY_AGENT_ID")
    if from_env:
        return from_env
    try:
        user = getpass.getuser()
    except (KeyError, OSError):  # pragma: no cover - exotic environments
        user = "unknown"
    return f"human-{user}"


def _fail(code: str, message: str) -> NoReturn:
    click.echo(f"Error: [{code}] {message}", err=True)
    sys.exit(1)


def _format_neurons(neurons: list[str], limit: int = 3) -> str:
    if not neurons:
        return "—"
    shown = neurons[:limit]
    text = ", ".join(shown)
    if len(neurons) > limit:
        text += f" (+{len(neurons) - limit} more)"
    return text


# ---------------------------------------------------------------------------
# cerebrofy who
# ---------------------------------------------------------------------------


@click.command("who")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def who_command(fmt: str) -> None:
    """Show all active agents, their claims, and overlapping claims."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        agents = registry.get_active_agents()
        overlapping = registry.detect_overlapping_claims()
    finally:
        registry.close()

    rows = [
        {
            "agent_id": agent_id,
            "agent_type": data["agent_type"],
            "intent": data["intent"],
            "claimed_neurons": data["claimed_neurons"],
            "active_minutes": data["active_minutes"],
            "session_id": data["session_id"],
        }
        for agent_id, data in agents.items()
    ]
    payload = {
        "active_agents": rows,
        "conflicts": overlapping,
        "total_active": len(rows),
    }

    if fmt == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    if not rows:
        click.echo("No active agents.")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    table.add_column("Agent", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Intent")
    table.add_column("Claims", style="green")
    table.add_column("Active", justify="right")
    for row in rows:
        intent = row["intent"]
        table.add_row(
            row["agent_id"],
            row["agent_type"],
            intent[:48] + ("…" if len(intent) > 48 else ""),
            _format_neurons(row["claimed_neurons"]),
            f"{row['active_minutes']}m",
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} active agent(s).[/dim]")


# ---------------------------------------------------------------------------
# cerebrofy claim
# ---------------------------------------------------------------------------


@click.command("claim")
@click.argument("neurons", nargs=-1, required=True)
@click.option(
    "--intent",
    default=None,
    help="What you are about to do (shown to other agents).",
)
@click.option("--agent-id", default=None, help="Acting agent id.")
@click.option(
    "--agent-type",
    default=None,
    help="Agent type (claude/cursor/devin/human/ci).",
)
@click.option(
    "--ttl-minutes",
    default=DEFAULT_TTL_MINUTES,
    show_default=True,
    type=click.IntRange(1, MAX_TTL_MINUTES),
    help="Claim lifetime before auto-release.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def claim_command(
    neurons: tuple[str, ...],
    intent: str | None,
    agent_id: str | None,
    agent_type: str | None,
    ttl_minutes: int,
    fmt: str,
) -> None:
    """Claim NEURONS (file paths or specific ``file::neuron`` ids)."""
    root = _resolve_root()
    acting_agent = _agent_id(agent_id)
    expanded = expand_neurons(root, list(neurons))
    effective_intent = intent or f"claiming {len(expanded)} neuron(s)"

    registry = _open_registry(root)
    try:
        result = registry.claim_neurons(
            acting_agent,
            expanded,
            effective_intent,
            agent_type=agent_type,
            ttl_minutes=ttl_minutes,
        )
    finally:
        registry.close()

    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
        if result.get("error") == NEURON_ALREADY_CLAIMED:
            sys.exit(1)
        return

    for conflict in result["conflicts"]:
        console.print(
            f"  • [bold]{conflict['neuron']}[/bold] — held by "
            f"[cyan]{conflict['existing_claimant']}[/cyan] "
            f"({conflict['claimant_intent']})"
        )
    if result.get("error") == NEURON_ALREADY_CLAIMED:
        _fail(
            NEURON_ALREADY_CLAIMED,
            f"all requested neurons are already claimed by another active agent "
            f"({acting_agent}).",
        )
    if result["conflicts"]:
        console.print(
            f"[yellow]{len(result['conflicts'])} neuron(s) skipped due to conflicts.[/yellow]"
        )
    console.print(f"[green]Claimed {len(result['claimed'])} neuron(s).[/green]")


# ---------------------------------------------------------------------------
# cerebrofy release
# ---------------------------------------------------------------------------


@click.command("release")
@click.argument("neurons", nargs=-1)
@click.option("--agent-id", default=None, help="Acting agent id.")
@click.option(
    "--all",
    "release_all_claims",
    is_flag=True,
    help="Release every claim held by the agent (the default with no NEURONS).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def release_command(
    neurons: tuple[str, ...],
    agent_id: str | None,
    release_all_claims: bool,
    fmt: str,
) -> None:
    """Release NEURONS, or every claim when NEURONS is omitted / --all is given."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        if release_all_claims or not neurons:
            result = registry.release_all(_agent_id(agent_id))
        else:
            expanded = expand_neurons(root, list(neurons))
            result = registry.release_neurons(_agent_id(agent_id), expanded)
    except CerebrofyError as exc:
        _fail(exc.code, str(exc))
    finally:
        registry.close()

    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
        return

    released = result.get("released") or []
    console.print(f"[green]Released {len(released)} neuron(s).[/green]")


# ---------------------------------------------------------------------------
# cerebrofy conflicts
# ---------------------------------------------------------------------------


@click.command("conflicts")
@click.option("--neuron", default=None, help="Limit the scan to one neuron.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def conflicts_command(neuron: str | None, fmt: str) -> None:
    """Show memory contradictions and overlapping neuron claims."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        detector = ConflictDetector(registry, memories_db_path=_memories_path(root))
        memory_conflicts = detector.detect_memory_conflicts(neuron)
        overlapping = detector.detect_overlapping_claims()
    finally:
        registry.close()

    payload = {
        "memory_conflicts": memory_conflicts,
        "overlapping_claims": overlapping,
    }

    if fmt == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    if not memory_conflicts and not overlapping:
        click.echo("No conflicts detected.")
        return

    if overlapping:
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        table.add_column("Neuron", style="cyan")
        table.add_column("Agents", style="magenta")
        for conflict in overlapping:
            table.add_row(conflict["neuron"], ", ".join(conflict["agents"]))
        console.print(table)

    for conflict in memory_conflicts:
        console.print(
            f"[yellow]{conflict['neuron']}[/yellow]: "
            f"{conflict['memory_a']['id']} vs {conflict['memory_b']['id']} "
            f"([dim]{conflict['type']}[/dim])"
        )


# ---------------------------------------------------------------------------
# cerebrofy resolve
# ---------------------------------------------------------------------------


@click.command("resolve")
@click.argument("memory_a")
@click.argument("memory_b")
@click.option(
    "--keep",
    "strategy_name",
    type=click.Choice(["newest", "author", "human-review"]),
    default="newest",
    show_default=True,
    help="Resolution strategy (default: keep newest).",
)
@click.option(
    "--merge",
    "do_merge",
    is_flag=True,
    help="Merge both memories into a new one (requires --body).",
)
@click.option("--body", default=None, help="Merged memory body (required with --merge).")
@click.option("--author", default=None, help="Author to keep (required with --keep author).")
@click.option("--neuron", default=None, help="Neuron the memories belong to.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def resolve_command(
    memory_a: str,
    memory_b: str,
    strategy_name: str,
    do_merge: bool,
    body: str | None,
    author: str | None,
    neuron: str | None,
    fmt: str,
) -> None:
    """Resolve the conflict between two memories."""
    if do_merge and not body:
        _fail(CONFIG_ERROR, "--body is required with --merge.")
    if not do_merge and strategy_name == "author" and not author:
        _fail(CONFIG_ERROR, "--author is required with '--keep author'.")

    strategy = "merge" if do_merge else strategy_name
    root = _resolve_root()
    resolver = ConflictResolver(root / ".cerebrofy", memories_db_path=_memories_path(root))
    try:
        result = resolver.resolve_pair(
            memory_a,
            memory_b,
            strategy,
            neuron=neuron,
            author=author,
            merged_body=body,
        )
    except ValueError as exc:
        _fail(CONFIG_ERROR, str(exc))

    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
        return

    if result.get("requires_review"):
        console.print(
            f"[yellow]Flagged for human review[/yellow]: "
            f"{result['memory_a']['id']} vs {result['memory_b']['id']}"
        )
        console.print("[dim]No memories were modified.[/dim]")
        return

    if result.get("strategy") == "merge":
        console.print(f"[green]Merged[/green] into {result['winner']}.")
        console.print(
            f"  superseded: {', '.join(result.get('superseded', []))}"
        )
        return

    console.print(
        f"[green]Kept[/green] {result['winner']}; marked {result['loser']} stale."
    )


# ---------------------------------------------------------------------------
# cerebrofy coordination metrics
# ---------------------------------------------------------------------------


@click.command("metrics")
@click.option(
    "--since",
    default=None,
    help="Show metrics since timestamp (unix epoch).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def metrics_command(since: str | None, fmt: str) -> None:
    """Show coordination metrics and observability data."""
    root = _resolve_root()

    # In-memory metrics
    mem_metrics = get_metrics()
    mem_snapshot = mem_metrics.snapshot()

    # Persistent metrics
    persistent = get_persistent_metrics(root / ".cerebrofy")
    since_ts = int(since) if since else None
    persistent_summary = persistent.get_summary(since_ts)

    payload = {
        "in_memory": mem_snapshot,
        "persistent": persistent_summary,
    }

    if fmt == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    # Text output
    console.print("[bold]Coordination Metrics[/bold]")
    console.print()

    console.print("[cyan]In-Memory (this process)[/cyan]")
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    for key, value in mem_snapshot.items():
        if key != "resolutions":
            table.add_row(key.replace("_", " ").title(), str(value))
    console.print(table)

    if mem_snapshot["resolutions"]:
        console.print()
        table2 = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        table2.add_column("Strategy", style="magenta")
        table2.add_column("Count", justify="right")
        for strategy, count in mem_snapshot["resolutions"].items():
            table2.add_row(strategy, str(count))
        console.print(table2)

    console.print()
    console.print("[cyan]Persistent (cross-process)[/cyan]")
    table3 = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    table3.add_column("Event Type", style="green")
    table3.add_column("Count", justify="right")
    for etype, count in persistent_summary["by_type"].items():
        table3.add_row(etype, str(count))
    console.print(table3)

    if persistent_summary["by_strategy"]:
        console.print()
        table4 = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        table4.add_column("Strategy", style="magenta")
        table4.add_column("Count", justify="right")
        for strategy, count in persistent_summary["by_strategy"].items():
            table4.add_row(strategy, str(count))
        console.print(table4)

    if persistent_summary["recent"]:
        console.print()
        console.print("[dim]Recent events (last 100):[/dim]")
        for event in persistent_summary["recent"][:20]:
            detail = event["details"] or ""
            subtype = f" [{event['event_subtype']}]" if event['event_subtype'] else ""
            console.print(
                f"  {event['created_ts']} | {event['event_type']}{subtype} | {detail}"
            )


# ---------------------------------------------------------------------------
# Alias group: cerebrofy coordination <subcommand>
# ---------------------------------------------------------------------------


@click.group("coordination")
def coordination_group() -> None:
    """Coordinate concurrent agents (alias for the top-level commands)."""


for _command in (
    who_command,
    claim_command,
    release_command,
    conflicts_command,
    resolve_command,
    metrics_command,
):
    coordination_group.add_command(_command)


__all__ = [
    "claim_command",
    "conflicts_command",
    "coordination_group",
    "metrics_command",
    "release_command",
    "resolve_command",
    "who_command",
]
