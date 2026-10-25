"""CLI command for Cross-Session Synthesizer."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import rich_click as click
from rich.console import Console

from cerebrofy.memory.store import open_memories_db
from cerebrofy.synthesizer import (
    list_synthesized_patterns,
    sessions_until_next_synthesis,
    synthesis_interval,
    synthesize,
)

console = Console()


def _find_cerebrofy_dir() -> Path | None:
    """Find .cerebrofy directory, return None if not found."""
    root = Path.cwd()
    dir_path = root / ".cerebrofy"
    if dir_path.exists():
        return dir_path
    return None


def _print_existing_patterns(cerebrofy_dir: Path, min_confidence: float) -> None:
    """Print persisted patterns, filtered by persisted confidence (M7)."""
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not memories_db.exists():
        console.print("[dim]No memories database found.[/dim]")
        return

    conn = open_memories_db(cerebrofy_dir)
    try:
        patterns = [
            pattern
            for pattern in list_synthesized_patterns(conn)
            if pattern.confidence >= min_confidence
        ]
    finally:
        conn.close()

    if not patterns:
        console.print("[dim]No synthesized patterns found.[/dim]")
        return

    for pattern in patterns:
        lobe = f" [{pattern.lobe}]" if pattern.lobe else ""
        console.print(f"  [cyan]{pattern.type}[/cyan]{lobe} — {pattern.title}")
        console.print(
            f"    Confidence: {pattern.confidence:.0%} | "
            f"Sample: {pattern.sample_size}/{pattern.sessions_analyzed}"
        )
        console.print(f"    Created: {time.ctime(pattern.created_ts)}")
        console.print("")


@click.command()
@click.option(
    "--min-sessions",
    "min_sessions",
    type=int,
    default=10,
    help="Minimum sessions before synthesis fires",
)
@click.option("--show", "show_patterns", is_flag=True, help="Show existing synthesized patterns")
@click.option(
    "--confidence",
    "min_confidence",
    type=float,
    default=0.7,
    help="Minimum confidence 0-1",
)
@click.option("--run", "run_now", is_flag=True, help="Force synthesis run now (explicit alias)")
def cerebrofy_synthesize(
    min_sessions: int,
    show_patterns: bool,
    min_confidence: float,
    run_now: bool,
) -> None:
    """Run cross-session pattern synthesis or show existing patterns."""
    cerebrofy_dir = _find_cerebrofy_dir()
    if cerebrofy_dir is None:
        console.print(
            "[red]Error: [NO_INDEX] .cerebrofy not found. Run 'cerebrofy build' first.[/red]"
        )
        sys.exit(1)

    sessions_db = cerebrofy_dir / "db" / "sessions.db"
    if not sessions_db.exists():
        console.print(
            "[yellow]Warning: [NO_SESSION_RECORDER] Session recording not enabled. "
            "Set 'record_sessions: true' in .cerebrofy/config.yaml.[/yellow]"
        )
        sys.exit(1)

    # m3: --show is read-only; bare `synthesize` runs; --run is an explicit alias.
    if show_patterns and not run_now:
        _print_existing_patterns(cerebrofy_dir, min_confidence)
        return

    console.print("[cyan]Running Cross-Session Synthesis...[/cyan]")
    result = synthesize(
        cerebrofy_dir,
        min_sessions=min_sessions,
        min_confidence=min_confidence,
    )
    patterns = [p for p in result.patterns if p.confidence >= min_confidence]
    if patterns:
        console.print(
            f"[green]Found {len(result.patterns)} pattern(s); "
            f"{result.written} written, {result.updated} updated "
            f"({len(patterns)} shown).[/green]"
        )
        for pattern in patterns:
            console.print(f"  [cyan]{pattern.type}[/cyan] — {pattern.title}")
            console.print(
                f"    Confidence: {pattern.confidence:.0%} | "
                f"Sample: {pattern.sample_size}/{pattern.sessions_analyzed}"
            )
            console.print(f"    {pattern.body}")
            console.print("")
    else:
        console.print(
            "[dim]No patterns found (may need more sessions or lower confidence threshold).[/dim]"
        )

    every_n = synthesis_interval(cerebrofy_dir)
    console.print(
        f"[dim]Next automatic run in "
        f"{sessions_until_next_synthesis(cerebrofy_dir, every_n)} session(s).[/dim]"
    )


if __name__ == "__main__":
    cerebrofy_synthesize()
