"""cerebrofy coordination — multi-agent coordination CLI (Idea #25).

Lets several agents (and humans) work on one codebase without silently undoing
each other: claim neurons before editing them, see who else is active, and
resolve contradicting memories.

The registry lives in the local index database (`.cerebrofy/db/cerebrofy.db`),
so claims are visible to every Cerebrofy process on this machine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import rich_click as click
from rich import box
from rich.console import Console
from rich.table import Table

from cerebrofy.coordination.conflict_detector import ConflictDetector
from cerebrofy.coordination.registry import ActiveAgentRegistry
from cerebrofy.coordination.resolver import ConflictResolver, ResolutionStrategy
from cerebrofy.errors import (
    NEURON_ALREADY_CLAIMED,
    NO_ACTIVE_AGENT,
)

console = Console()


def _resolve_root() -> Path:
    """Resolve the repo root via the shared pure finder; exit the CLI on failure."""
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


def _open_registry(root: Path) -> ActiveAgentRegistry:
    """Open the registry against the local index, exiting cleanly when absent."""
    db_path = _index_path(root)
    if not db_path.exists():
        click.echo(
            "Error: Index not found. Run 'cerebrofy build' first.", err=True
        )
        sys.exit(1)
    return ActiveAgentRegistry(str(db_path))


def _agent_id(explicit: str | None) -> str:
    """Resolve the acting agent id, falling back to the environment."""
    if explicit:
        return explicit
    return click.get_current_context().find_root().params.get("agent_id") or "local-agent"


def _format_neurons(neurons: list[str], limit: int = 3) -> str:
    if not neurons:
        return "—"
    shown = neurons[:limit]
    text = ", ".join(shown)
    if len(neurons) > limit:
        text += f" (+{len(neurons) - limit} more)"
    return text


# ---------------------------------------------------------------------------
# cerebrofy coordination group
# ---------------------------------------------------------------------------

@click.group("coordination")
def coordination_group() -> None:
    """Coordinate concurrent agents: claim neurons, see peers, resolve conflicts."""


# ---------------------------------------------------------------------------
# cerebrofy coordination who
# ---------------------------------------------------------------------------

@coordination_group.command("who")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def coordination_who(fmt: str) -> None:
    """Show all active agents and the neurons they have claimed."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        agents = registry.get_active_agents()
    finally:
        registry.close()

    now = int(__import__("time").time())
    rows = []
    for agent_id, data in agents.items():
        rows.append(
            {
                "agent_id": agent_id,
                "agent_type": data["agent_type"],
                "intent": data["intent"] or "",
                "claimed_neurons": data["claimed_neurons"],
                "active_minutes": (now - data["started_ts"]) // 60,
                "session_id": data["session_id"],
            }
        )

    if fmt == "json":
        click.echo(json.dumps({"active_agents": rows, "total_active": len(rows)}, indent=2))
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
        table.add_row(
            row["agent_id"],
            row["agent_type"],
            row["intent"][:48] + ("…" if len(row["intent"]) > 48 else ""),
            _format_neurons(row["claimed_neurons"]),
            f"{row['active_minutes']}m",
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} active agent(s).[/dim]")


# ---------------------------------------------------------------------------
# cerebrofy coordination claim / release
# ---------------------------------------------------------------------------

@coordination_group.command("claim")
@click.argument("neurons", nargs=-1, required=True)
@click.option("--intent", required=True,
              help="What you are about to do (shown to other agents).")
@click.option("--agent-id", default=None, help="Acting agent id (default: local-agent).")
@click.option("--ttl-minutes", default=60, show_default=True,
              help="Claim lifetime before auto-release.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def coordination_claim(
    neurons: tuple[str, ...],
    intent: str,
    agent_id: str | None,
    ttl_minutes: int,
    fmt: str,
) -> None:
    """Claim NEURONS (ids or file paths) for the acting agent."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        result = registry.claim_neurons(
            _agent_id(agent_id), list(neurons), intent, ttl_minutes=ttl_minutes
        )
    finally:
        registry.close()

    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
        return

    if result["conflicts"]:
        console.print(f"[yellow]Conflicts on {len(result['conflicts'])} neuron(s):[/yellow]")
        for conflict in result["conflicts"]:
            for other in conflict["claiming_agents"]:
                console.print(
                    f"  • [bold]{conflict['neuron']}[/bold] — held by "
                    f"[cyan]{other['agent_id']}[/cyan] ({other['intent']})"
                )
    console.print(f"[green]Claimed {len(result['claimed'])} neuron(s).[/green]")


@coordination_group.command("release")
@click.argument("neurons", nargs=-1)
@click.option("--agent-id", default=None, help="Acting agent id (default: local-agent).")
@click.option("--all", "release_all", is_flag=True,
              help="Release every claim held by the agent.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def coordination_release(
    neurons: tuple[str, ...],
    agent_id: str | None,
    release_all: bool,
    fmt: str,
) -> None:
    """Release NEURONS claimed by the acting agent (all claims when --all)."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        if release_all:
            result = registry.release_all(_agent_id(agent_id))
        else:
            if not neurons:
                click.echo("Error: give neuron ids to release, or pass --all.", err=True)
                sys.exit(1)
            result = registry.release_neurons(_agent_id(agent_id), list(neurons))
    finally:
        registry.close()

    if result.get("error") == NO_ACTIVE_AGENT:
        click.echo(f"Error: [{NO_ACTIVE_AGENT}] no active agent with that id.", err=True)
        sys.exit(1)

    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
        return

    released = result.get("released") or []
    console.print(f"[green]Released {len(released)} neuron(s).[/green]")


# ---------------------------------------------------------------------------
# cerebrofy coordination conflicts / resolve
# ---------------------------------------------------------------------------

@coordination_group.command("conflicts")
@click.option("--neuron", default=None, help="Limit the scan to one neuron.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def coordination_conflicts(neuron: str | None, fmt: str) -> None:
    """Show claim collisions and contradicting memories needing resolution."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        detector = ConflictDetector(registry=registry)
        conflicts = registry.detect_overlapping_claims()
        memory_conflicts = registry.detect_memory_conflicts(neuron)
    finally:
        registry.close()

    payload = {
        "claim_conflicts": conflicts,
        "memory_conflicts": memory_conflicts,
    }

    if fmt == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    if not conflicts and not memory_conflicts:
        click.echo("No conflicts detected.")
        return

    if conflicts:
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        table.add_column("Neuron", style="cyan")
        table.add_column("Agents", style="magenta")
        for conflict in conflicts:
            table.add_row(conflict["neuron"], ", ".join(conflict["agents"]))
        console.print(table)

    for conflict in memory_conflicts:
        console.print(
            f"[yellow]{conflict['neuron']}[/yellow]: "
            f"{conflict['memory_a']['id']} vs {conflict['memory_b']['id']} "
            f"([dim]{conflict['type']}[/dim])"
        )


@coordination_group.command("resolve")
@click.argument("memory_a")
@click.argument("memory_b")
@click.option("--keep", "strategy", default="newest",
              type=click.Choice(["newest", "author", "review", "merge"]),
              show_default=True, help="Resolution strategy.")
@click.option("--neuron", default=None, help="Neuron the memories belong to.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def coordination_resolve(
    memory_a: str,
    memory_b: str,
    strategy: str,
    neuron: str | None,
    fmt: str,
) -> None:
    """Resolve the conflict between two memories."""
    root = _resolve_root()
    registry = _open_registry(root)
    try:
        resolver = ConflictResolver(registry=registry)
        mapping = {
            "newest": ResolutionStrategy.KEEP_MOST_RECENT,
            "author": ResolutionStrategy.KEEP_BY_AUTHOR,
            "review": ResolutionStrategy.HUMAN_REVIEW,
            "merge": ResolutionStrategy.MERGE,
        }
        result = resolver.resolve_pair(
            memory_a,
            memory_b,
            mapping[strategy],
            neuron=neuron,
        )
    finally:
        registry.close()

    if fmt == "json":
        click.echo(json.dumps(result, indent=2))
        return

    if result.get("error") == NEURON_ALREADY_CLAIMED:
        click.echo(f"Error: [{NEURON_ALREADY_CLAIMED}] {result['message']}", err=True)
        sys.exit(1)

    console.print(f"[green]Resolved[/green] with strategy [bold]{strategy}[/bold].")
    kept = result.get("resolved_memory")
    if kept:
        console.print(f"  kept: {kept.get('id')} — {kept.get('body', '')[:80]}")
    merged = result.get("merged_memory")
    if merged:
        console.print(f"  merged: {merged.get('id')}")


__all__ = ["coordination_group"]
