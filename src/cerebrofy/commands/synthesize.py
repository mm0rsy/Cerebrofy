"""CLI command for Cross-Session Synthesizer."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import rich_click as click
from rich.console import Console

from cerebrofy.synthesizer.analyzer import run_synthesis


console = Console()


def _find_cerebrofy_dir() -> Path | None:
    """Find .cerebrofy directory, return None if not found."""
    root = Path.cwd()
    dir_path = root / ".cerebrofy"
    if dir_path.exists():
        return dir_path
    return None


@click.command()
@click.option("--min-sessions", "min_sessions", type=int, default=10, help="Minimum sessions before synthesis fires")
@click.option("--show", "show_patterns", is_flag=True, help="Show all synthesized patterns")
@click.option("--confidence", "min_confidence", type=float, default=0.7, help="Minimum confidence 0-1")
@click.option("--run", "run_now", is_flag=True, help="Force synthesis run now")
def cerebrofy_synthesize(min_sessions: int, show_patterns: bool, min_confidence: float, run_now: bool) -> None:
    """Run cross-session pattern synthesis or show existing patterns."""
    cerebrofy_dir = _find_cerebrofy_dir()
    if cerebrofy_dir is None:
        console.print("[red]Error: [NO_INDEX] .cerebrofy not found. Run 'cerebrofy build' first.[/red]")
        sys.exit(1)

    sessions_db = cerebrofy_dir / "db" / "sessions.db"
    if not sessions_db.exists():
        console.print("[yellow]Warning: [NO_SESSION_RECORDER] Session recording not enabled. Enable in cerebrofy.yaml.[/yellow]")
        sys.exit(1)

    if run_now or not show_patterns:
        console.print("[cyan]Running Cross-Session Synthesis...[/cyan]")
        patterns = run_synthesis(cerebrofy_dir, min_sessions=min_sessions, min_confidence=min_confidence, run_now=True)
        if patterns:
            console.print(f"[green]Found {len(patterns)} pattern(s) ({len([p for p in patterns if p.confidence >= min_confidence])} written as memories).[/green]")
            for p in patterns:
                if p.confidence >= min_confidence:
                    console.print(f"  [cyan]{p.type}[/cyan] — {p.title}")
                    console.print(f"    Confidence: {p.confidence:.0%} | Sample: {p.sample_size}/{p.sessions_analyzed}")
                    console.print(f"    {p.body}")
                    console.print("")
        else:
            console.print("[dim]No patterns found (may need more sessions or lower confidence threshold).[/dim]")
    else:
        # Show existing patterns from memories
        memories_db = cerebrofy_dir / "db" / "memories.db"
        if memories_db.exists():
            conn = sqlite3.connect(memories_db)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE type = 'pattern' AND tags LIKE '%synthesized%' ORDER BY created_ts DESC LIMIT 50"
                ).fetchall()
                if rows:
                    for row in rows:
                        tags = row["tags"].split(",") if row["tags"] else []
                        p_type = next((t for t in tags if t != "synthesized"), "pattern")
                        console.print(f"  [cyan]{p_type}[/cyan] — {row['title']}")
                        console.print(f"    Created: {time.ctime(row['created_ts'])}")
                        console.print("")
                else:
                    console.print("[dim]No synthesized patterns found.[/dim]")
            finally:
                conn.close()
        else:
            console.print("[dim]No memories database found.[/dim]")


if __name__ == "__main__":
    cerebrofy_synthesize()