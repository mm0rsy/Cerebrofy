"""cerebrofy intent — product intent declaration commands."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import rich_click as click

from cerebrofy.config.loader import load_config


@click.group("intent")
def cerebrofy_intent() -> None:
    """Manage product intent declarations (sprint goals, incidents, architecture)."""


@cerebrofy_intent.command("init")
def intent_init() -> None:
    """Scaffold a new .cerebrofy/intent.yaml with commented sections."""
    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"

    if not config_path.exists():
        click.echo("Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.", err=True)
        sys.exit(1)

    intent_path = root / ".cerebrofy" / "intent.yaml"
    if intent_path.exists():
        click.echo(f"intent.yaml already exists at {intent_path}")
        click.echo("Use 'cerebrofy intent edit' to modify it, or delete it and re-run init.")
        sys.exit(1)

    from cerebrofy.intent.loader import scaffold_intent_yaml

    scaffold_intent_yaml(intent_path)
    click.echo(f"Created {intent_path}")
    click.echo("Edit it to reflect your current sprint goals, incidents, and architectural direction.")
    click.echo("Commit this file — it is shared across the team.")


@cerebrofy_intent.command("show")
@click.option(
    "--json", "as_json",
    is_flag=True, default=False,
    help="Output machine-readable JSON for agent consumption.",
)
def intent_show(as_json: bool) -> None:
    """Display the current product intent."""
    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"

    if not config_path.exists():
        click.echo("Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.", err=True)
        sys.exit(1)

    from cerebrofy.intent.loader import load_intent

    intent = load_intent(root / ".cerebrofy")
    if intent is None:
        click.echo("No intent.yaml found. Run 'cerebrofy intent init' to create one.", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(intent.to_dict(), indent=2))
        return

    click.echo("\n🎯 Cerebrofy — Product Intent\n")

    if intent.sprint:
        click.echo(f"  Sprint:     {intent.sprint.name}")
        click.echo(f"  Goal:       {intent.sprint.goal}")
        click.echo(f"  Deadline:   {intent.sprint.deadline}")
        if intent.sprint.priority_lobes:
            click.echo(f"  Priority:   {', '.join(intent.sprint.priority_lobes)}")
        if intent.sprint.deprioritized_lobes:
            click.echo(f"  Low-pri:    {', '.join(intent.sprint.deprioritized_lobes)}")
    else:
        click.echo("  No sprint defined.")

    if intent.incidents:
        click.echo(f"\n  Active Incidents ({len(intent.incidents)}):")
        for inc in intent.incidents:
            status_icon = "🔴" if inc.severity == "critical" else "🟡"
            click.echo(f"    {status_icon} [{inc.id}] {inc.description} ({inc.status})")
            if inc.lesson:
                click.echo(f"       Lesson: {inc.lesson}")

    if intent.architecture:
        click.echo(f"\n  Architecture: {intent.architecture.direction}")
        for pattern in intent.architecture.avoid_patterns:
            click.echo(f"    ⛔ AVOID: {pattern}")
        for principle in intent.architecture.principles:
            click.echo(f"    ✅ {principle}")

    if intent.team_context:
        if intent.team_context.concerns:
            click.echo("\n  Team Concerns:")
            for concern in intent.team_context.concerns:
                click.echo(f"    ⚠️  {concern}")
        if intent.team_context.upcoming_risks:
            click.echo("\n  Upcoming Risks:")
            for risk in intent.team_context.upcoming_risks:
                click.echo(f"    📅 {risk}")

    click.echo()


@cerebrofy_intent.command("edit")
def intent_edit() -> None:
    """Open intent.yaml in $EDITOR."""
    root = Path.cwd()
    intent_path = root / ".cerebrofy" / "intent.yaml"

    if not intent_path.exists():
        click.echo("No intent.yaml found. Run 'cerebrofy intent init' to create one.", err=True)
        sys.exit(1)

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
    os.execvp(editor, [editor, str(intent_path)])


@cerebrofy_intent.command("validate")
def intent_validate() -> None:
    """Check intent.yaml syntax and validate lobe names against the codebase graph."""
    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"

    if not config_path.exists():
        click.echo("Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.", err=True)
        sys.exit(1)

    intent_path = root / ".cerebrofy" / "intent.yaml"
    if not intent_path.exists():
        click.echo("No intent.yaml found. Run 'cerebrofy intent init' to create one.", err=True)
        sys.exit(1)

    # Check YAML syntax
    try:
        from cerebrofy.intent.loader import load_intent
        intent = load_intent(root / ".cerebrofy")
    except Exception as exc:
        click.echo(f"Error: intent.yaml is malformed — {exc}", err=True)
        sys.exit(2)

    if intent is None:
        click.echo("intent.yaml is empty or could not be parsed.", err=True)
        sys.exit(2)

    # Validate lobe names against config
    config = load_config(config_path)
    known_lobes = set(config.lobes.keys())

    from cerebrofy.intent.loader import validate_intent
    warnings = validate_intent(intent, known_lobes)

    if warnings:
        click.echo("Validation warnings:")
        for w in warnings:
            click.echo(f"  ⚠️  {w}")
        sys.exit(1)
    else:
        click.echo("intent.yaml is valid. ✅")
