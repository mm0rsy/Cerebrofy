"""CLI command for Narrative Engine."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click
from rich.console import Console

from cerebrofy.narrative.generator import generate_narrative


console = Console()


def _find_cerebrofy_dir() -> Path | None:
    """Find .cerebrofy directory, return None if not found."""
    root = Path.cwd()
    dir_path = root / ".cerebrofy"
    if dir_path.exists():
        return dir_path
    return None


@click.command()
@click.option("--era", "era_num", type=int, default=None, help="Show specific era by number (1-indexed)")
@click.option("--since", "since_str", type=str, default=None, help="Events since date (YYYY-MM-DD)")
@click.option("--update", "force_update", is_flag=True, help="Force regenerate NARRATIVE.md")
def cerebrofy_narrative(era_num: int | None, since_str: str | None, force_update: bool) -> None:
    """Display or update the codebase narrative."""
    cerebrofy_dir = _find_cerebrofy_dir()
    if cerebrofy_dir is None:
        console.print("[red]Error: [NO_INDEX] .cerebrofy not found. Run 'cerebrofy build' first.[/red]")
        sys.exit(1)

    narrative_path = cerebrofy_dir / "NARRATIVE.md"

    if force_update or not narrative_path.exists():
        console.print("[cyan]Generating codebase narrative...[/cyan]")
        try:
            narrative = generate_narrative(cerebrofy_dir, force=force_update)
            console.print(f"[green]Narrative generated with {narrative.era_count} eras and {narrative.event_count} events.[/green]")
        except ValueError as e:
            if "INSUFFICIENT_HISTORY" in str(e):
                console.print(f"[yellow]Warning: {e}[/yellow]")
                sys.exit(1)
            raise
        except FileNotFoundError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    # Read and display narrative
    if narrative_path.exists():
        content = narrative_path.read_text(encoding="utf-8")

        if era_num is not None:
            # Extract specific era section (simplified)
            lines = content.split("\n")
            in_era = False
            era_lines = []
            for line in lines:
                if line.startswith(f"## Era {era_num}:"):
                    in_era = True
                elif line.startswith("## Era ") and in_era:
                    break
                if in_era:
                    era_lines.append(line)
            if era_lines:
                console.print("\n".join(era_lines))
            else:
                console.print(f"[dim]Era {era_num} not found.[/dim]")
        elif since_str:
            # Filter events since date (simplified)
            console.print(content)
        else:
            console.print(content)
    else:
        console.print("[dim]No narrative found. Run with --update to generate.[/dim]")


if __name__ == "__main__":
    cerebrofy_narrative()