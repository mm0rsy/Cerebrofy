"""cerebrofy plan — natural-language refactor planner (Idea #12).

Generates a graph-aware, step-by-step migration plan for a plain-English
refactoring description. The command never modifies files: execution is an
explicit handoff (``--execute``) to an AI agent that verifies each step with
``cerebrofy_impact``.
"""

from __future__ import annotations

import sys

import rich_click as click

from cerebrofy.planning.planner import NO_INDEX, PlanError, build_refactor_plan
from cerebrofy.search.hybrid import embed_query
from cerebrofy.utils.paths import InvalidRepoRootError, require_repo_root


@click.command("plan")
@click.argument("description")
@click.option(
    "--execute", is_flag=True, default=False,
    help="Prepare the execution handoff for an AI agent (no files are written).",
)
@click.option(
    "--output", type=click.Choice(["markdown", "json"]), default="markdown",
    show_default=True, help="Output format.",
)
def cerebrofy_plan(description: str, execute: bool, output: str) -> None:
    """Generate a step-by-step refactoring plan from DESCRIPTION.

    The description is matched against the semantic index, expanded into a
    cohesive neuron cluster, and sequenced into dependency-safe migration
    steps (new module skeleton → moves + re-export stubs → caller updates →
    stub removal). Nothing is modified until a plan is explicitly executed.

    \b
    Examples:
      cerebrofy plan "extract the payment logic into a payments service"
      cerebrofy plan "move all database connection code into a db/ module"
      cerebrofy plan "extract the auth helpers" --output json
      cerebrofy plan "extract the auth helpers" --execute
    """
    from cerebrofy.config.loader import load_config
    from cerebrofy.db.connection import open_db_readonly
    from cerebrofy.planning.formatter import plan_to_json, plan_to_markdown

    # Repo-root resolution is delegated to the shared pure finder
    # ``require_repo_root``; failure (missing project or a bad CEREBROFY_ROOT)
    # is handled here in the CLI layer with the existing user-facing message
    # and exit code, so command output and exit codes are unchanged.
    try:
        root = require_repo_root()
    except FileNotFoundError:
        click.echo(
            "Cerebrofy: [NO_INDEX] No .cerebrofy directory found. "
            "Run 'cerebrofy init && cerebrofy build' first."
        )
        sys.exit(1)
    except InvalidRepoRootError as exc:
        click.echo(f"Cerebrofy: {exc}", err=True)
        sys.exit(1)

    config_path = root / ".cerebrofy" / "config.yaml"
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo(
            f"Cerebrofy: [{NO_INDEX}] Index not found. "
            "Run 'cerebrofy build' first."
        )
        sys.exit(1)

    config = load_config(config_path)
    try:
        embedding = embed_query(description, config.embedding_model)
    except ValueError as err:
        click.echo(f"Cerebrofy: {err}")
        sys.exit(1)

    conn = open_db_readonly(db_path)
    try:
        plan = build_refactor_plan(
            description=description,
            conn=conn,
            embedding=embedding,
            repo_root=root,
            config_path=config_path,
            dry_run=not execute,
        )
    except PlanError as err:
        click.echo(f"Cerebrofy: [{err.code}] {err.message}")
        sys.exit(1)
    finally:
        conn.close()

    if output == "json":
        click.echo(plan_to_json(plan))
    else:
        click.echo(plan_to_markdown(plan))
