"""cerebrofy context — budget-aware context window optimizer."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.table import Table
from rich import box

from cerebrofy.context.optimizer import ContextPlan

console = Console()

_TIER_ICON = {
    "full_source": "📄",
    "signature_only": "✏️",
    "lobe_summary": "📦",
    "name_only": "🔖",
}


def _open_paths(root: Path) -> tuple[Path, Path]:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    config_path = root / ".cerebrofy" / "config.yaml"
    if not db_path.exists():
        click.echo("Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' first.")
        sys.exit(1)
    return db_path, config_path


def _render_text(plan: ContextPlan) -> None:
    console.print()
    console.print(f"[bold]🧠 Cerebrofy — Context Plan[/bold]: [cyan]{plan.task}[/cyan]")
    console.print(
        f"Budget: [bold]{plan.token_budget}[/bold] | "
        f"Used: [bold]{plan.tokens_used}[/bold] | "
        f"Neurons: [bold]{len(plan.neurons)}[/bold] | "
        f"Truncated: [bold]{plan.truncated_count}[/bold]"
    )

    if plan.epistemic and plan.epistemic.caveats:
        for caveat in plan.epistemic.caveats:
            console.print(f"[yellow]⚠️  {caveat}[/yellow]")

    console.print()
    t = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    t.add_column("Tier")
    t.add_column("Neuron")
    t.add_column("File")
    t.add_column("Score", justify="right")
    t.add_column("Tokens", justify="right")
    t.add_column("Source")

    for n in plan.neurons:
        t.add_row(
            f"{_TIER_ICON.get(n.inclusion_tier, '•')} {n.inclusion_tier}",
            n.name,
            f"{n.file}:{n.line_start}",
            f"{n.relevance_score:.3f}",
            str(n.tokens),
            n.source,
        )

    console.print(t)

    if plan.lobe_summaries_included:
        console.print(f"Lobe summaries: {', '.join(plan.lobe_summaries_included)}")


@click.command("context")
@click.argument("task")
@click.option("--budget", default=8000, show_default=True, help="Token budget.")
@click.option("--model", default="auto", show_default=True,
              help="Model for token counting (e.g. gpt-4o, claude-sonnet-4-6).")
@click.option("--output", type=click.Choice(["text", "json", "markdown", "claude-xml"]),
              default="text", show_default=True, help="Output format.")
def cerebrofy_context(task: str, budget: int, model: str, output: str) -> None:
    """Build the optimal context window for TASK within a token BUDGET.

    \b
    Examples:
      cerebrofy context "add rate limiting to the login endpoint" --budget 8000
      cerebrofy context "fix the JWT refresh bug" --budget 32000 --output json
      cerebrofy context "refactor the embedder" --output claude-xml
    """
    from cerebrofy.context.exporter import to_claude_xml, to_json, to_markdown
    from cerebrofy.context.optimizer import optimize_context

    root = Path.cwd()
    db_path, config_path = _open_paths(root)

    try:
        plan = optimize_context(
            task=task,
            db_path=db_path,
            config_path=config_path,
            budget=budget,
            model=model,
            repo_root=root,
        )
    except ValueError as err:
        click.echo(f"Cerebrofy: {err}")
        sys.exit(1)

    if output == "json":
        click.echo(to_json(plan))
    elif output == "markdown":
        click.echo(to_markdown(plan))
    elif output == "claude-xml":
        click.echo(to_claude_xml(plan))
    else:
        _render_text(plan)
