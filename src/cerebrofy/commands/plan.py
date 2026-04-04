"""cerebrofy plan — offline hybrid search impact reporter (Markdown/JSON)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from cerebrofy.search.hybrid import HybridSearchResult


def _format_plan_markdown(result: HybridSearchResult) -> str:
    """Render a HybridSearchResult as a structured Markdown impact report."""
    lines: list[str] = []
    lines.append(f"# Cerebrofy Plan: {result.query}\n")

    lines.append("## Matched Neurons\n")
    lines.append("| # | Name | File | Line | Similarity |")
    lines.append("|---|------|------|------|------------|")
    for i, n in enumerate(result.matched_neurons, 1):
        lines.append(f"| {i} | {n.name} | {n.file} | {n.line_start} | {n.similarity:.2f} |")
    lines.append("")

    lines.append("## Blast Radius (depth-2 neighbors)\n")
    lines.append("| Name | File | Line |")
    lines.append("|------|------|------|")
    for br in result.blast_radius:
        lines.append(f"| {br.name} | {br.file} | {br.line_start} |")
    lines.append("")

    if result.runtime_boundary_warnings:
        lines.append("## RUNTIME_BOUNDARY Warnings\n")
        for w in result.runtime_boundary_warnings:
            lines.append(f"- {w.src_name} ({w.src_file}) → unresolvable cross-language call")
        lines.append("")

    lines.append("## Affected Lobes\n")
    lines.append("| Lobe | File |")
    lines.append("|------|------|")
    for lobe_name in sorted(result.affected_lobe_files.keys()):
        lines.append(f"| {lobe_name} | {result.affected_lobe_files[lobe_name]} |")
    lines.append("")

    lines.append("## Re-index Scope\n")
    lines.append(
        f"Estimated **{result.reindex_scope} nodes** would need re-indexing for changes in this area."
    )
    lines.append("")

    return "\n".join(lines)


def _format_plan_json(result: HybridSearchResult) -> str:
    """Render a HybridSearchResult as a stable JSON impact report."""
    d = {
        "schema_version": 1,
        "matched_neurons": [
            {
                "id": n.id,
                "name": n.name,
                "file": n.file,
                "line_start": n.line_start,
                "similarity": round(n.similarity, 2),
            }
            for n in result.matched_neurons
        ],
        "blast_radius": [
            {"id": n.id, "name": n.name, "file": n.file, "line_start": n.line_start}
            for n in result.blast_radius
        ],
        "affected_lobes": sorted(list(result.affected_lobes)),
        "reindex_scope": result.reindex_scope,
    }
    return json.dumps(d, indent=2)


@click.command("plan")
@click.argument("description")
@click.option("--top-k", default=None, type=int, help="Override KNN top-k for this run.")
@click.option(
    "--json", "output_json", is_flag=True, default=False,
    help="Output machine-readable JSON instead of Markdown.",
)
def cerebrofy_plan(description: str, top_k: int | None, output_json: bool) -> None:
    """Run hybrid search and output an offline impact report (Markdown or JSON)."""
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
    result = hybrid_search(
        query=description,
        db_path=str(db_path),
        embedding=embedding,
        top_k=effective_top_k,
        config_embed_model=config.embedding_model,
        lobe_dir=lobe_dir,
    )

    if not result.matched_neurons:
        click.echo("Cerebrofy: No relevant code units found for this description.")
        sys.exit(0)

    if output_json:
        click.echo(_format_plan_json(result))
    else:
        click.echo(_format_plan_markdown(result))

    sys.exit(0)
