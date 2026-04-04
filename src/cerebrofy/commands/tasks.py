"""cerebrofy tasks — offline numbered task list from hybrid search."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import click

from cerebrofy.search.hybrid import HybridSearchResult, MatchedNeuron


@dataclass(frozen=True)
class TaskItem:
    """A single task item in the cerebrofy tasks output."""

    index: int
    neuron: MatchedNeuron
    lobe_name: str
    blast_count: int


def _build_task_items(
    result: HybridSearchResult,
) -> tuple[list[TaskItem], list[str]]:
    """Build task items and RUNTIME_BOUNDARY notes from a HybridSearchResult."""
    items: list[TaskItem] = []

    for i, neuron in enumerate(result.matched_neurons):
        # Derive lobe name from the first path component (same logic as _resolve_affected_lobes)
        parts = neuron.file.split("/")
        file_lobe = parts[0] if len(parts) > 1 else "root"

        # Match against affected_lobe_files keys (prefer exact match)
        if file_lobe in result.affected_lobe_files:
            lobe_name = file_lobe
        elif result.affected_lobe_files:
            lobe_name = next(iter(sorted(result.affected_lobe_files.keys())))
        else:
            lobe_name = "(unassigned)"

        items.append(TaskItem(
            index=i + 1,
            neuron=neuron,
            lobe_name=lobe_name,
            blast_count=result.per_neuron_blast_counts.get(neuron.id, 0),
        ))

    notes: list[str] = [
        f"Note: {w.src_name} has unresolvable cross-language calls "
        f"— see RUNTIME_BOUNDARY entries in [[{w.lobe_name}]]."
        for w in result.runtime_boundary_warnings
    ]

    return items, notes


def _format_tasks_markdown(
    items: list[TaskItem], notes: list[str], description: str
) -> str:
    """Render task items as a numbered Markdown list."""
    lines: list[str] = [f"# Cerebrofy Tasks: {description}\n"]
    for item in items:
        lines.append(
            f"{item.index}. Modify {item.neuron.name} in [[{item.lobe_name}]] "
            f"({item.neuron.file}:{item.neuron.line_start}) "
            f"— blast radius: {item.blast_count} nodes"
        )
    if notes:
        lines.append("")
        for note in notes:
            lines.append(note)
    return "\n".join(lines) + "\n"


@click.command("tasks")
@click.argument("description")
@click.option("--top-k", default=None, type=int, help="Override KNN top-k for this run.")
def cerebrofy_tasks(description: str, top_k: int | None) -> None:
    """Run hybrid search and output a numbered task list (offline, no LLM)."""
    if not description:
        click.echo("Description must not be empty.", err=True)
        sys.exit(1)

    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    if not db_path.exists():
        click.echo("No index found. Run 'cerebrofy build' first.", err=True)
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        from cerebrofy.db.connection import check_schema_version
        try:
            check_schema_version(conn)
        except ValueError:
            click.echo(
                "Schema version mismatch. Run 'cerebrofy migrate' to upgrade.",
                err=True,
            )
            sys.exit(1)
    finally:
        conn.close()

    from cerebrofy.config.loader import load_config
    config = load_config(config_path)
    effective_top_k = top_k or config.top_k or 10

    from cerebrofy.search.hybrid import _embed_query, hybrid_search
    embedding = _embed_query(description, config)

    lobe_dir = str(root / "docs" / "cerebrofy")
    try:
        result = hybrid_search(
            query=description,
            db_path=str(db_path),
            embedding=embedding,
            top_k=effective_top_k,
            config_embed_model=config.embedding_model,
            lobe_dir=lobe_dir,
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not result.matched_neurons:
        click.echo("Cerebrofy: No relevant code units found for this description.")
        sys.exit(0)

    items, notes = _build_task_items(result)
    click.echo(_format_tasks_markdown(items, notes, description))
    sys.exit(0)
