"""cerebrofy memory — writable agent memory store CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import sqlite3

import rich_click as click
from rich import box
from rich.console import Console
from rich.table import Table

console = Console()


def _get_author(override: str | None) -> str:
    if override:
        return override
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=3,
        )
        email = result.stdout.strip()
        if email:
            return f"human:{email}"
    except Exception:
        pass
    return "human:unknown"


def _open(root: Path) -> "sqlite3.Connection":
    from cerebrofy.memory.store import open_memories_db
    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "config.yaml").exists():
        click.echo("Error: Not initialized. Run 'cerebrofy init' first.", err=True)
        sys.exit(1)
    (cerebrofy_dir / "db").mkdir(parents=True, exist_ok=True)
    return open_memories_db(cerebrofy_dir)


@click.group("memory")
def mem_group() -> None:
    """Read and write structured memories attached to your codebase."""


@mem_group.command("add")
@click.argument("title")
@click.option("--type", "mem_type", required=True,
              type=click.Choice(["decision", "warning", "context", "pattern", "agent_action"]),
              help="Memory type.")
@click.option("--body", required=True, help="Full memory content.")
@click.option("--neuron", default=None, help="Neuron to attach to (file::name or name).")
@click.option("--lobe", default=None, help="Lobe name to attach to.")
@click.option("--tags", default=None, help="Comma-separated tags.")
@click.option("--author", default=None, help="Author string. Defaults to git config user.email.")
def memory_add(title: str, mem_type: str, body: str, neuron: str | None,
               lobe: str | None, tags: str | None, author: str | None) -> None:
    """Add a structured memory to the codebase index."""
    from cerebrofy.memory.embedder import embed_memory
    from cerebrofy.memory.store import Memory, write_memory

    root = Path.cwd()
    conn = _open(root)

    neuron_id: str | None = None
    if neuron:
        db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
        try:
            from cerebrofy.db.connection import open_db
            idx = open_db(db_path)
            rows = idx.execute(
                "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                (neuron, f"%::{neuron}"),
            ).fetchall()
            idx.close()
            if not rows:
                click.echo(
                    f"Warning: neuron '{neuron}' not found — memory stored without anchor.",
                    err=True,
                )
            elif len(rows) > 1:
                matches = ", ".join(r[0] for r in rows[:5])
                click.echo(
                    f"Warning: '{neuron}' matches {len(rows)} neurons ({matches}…) — "
                    f"using first match. Use file::name for precision.",
                    err=True,
                )
                neuron_id = rows[0][0]
            else:
                neuron_id = rows[0][0]
        except Exception:
            pass

    tag_tuple = tuple(t.strip() for t in tags.split(",") if t.strip()) if tags else ()
    mem = Memory(
        id=str(uuid.uuid4()),
        neuron_id=neuron_id,
        lobe=lobe,
        type=mem_type,
        title=title,
        body=body,
        author=_get_author(author),
        created_ts=int(time.time()),
        tags=tag_tuple,
        decay_score=1.0,
        status="active",
    )
    embedding = embed_memory(title, body)
    write_memory(conn, mem, embedding)
    conn.commit()
    conn.close()
    click.echo(mem.id)


@mem_group.command("search")
@click.argument("query")
@click.option("--type", "mem_type", default=None, help="Filter by type.")
@click.option("--lobe", default=None, help="Filter by lobe.")
@click.option("--limit", default=10, show_default=True, help="Max results.")
@click.option("--include-stale", is_flag=True, default=False, help="Include stale memories.")
def memory_search(query: str, mem_type: str | None, lobe: str | None,
                  limit: int, include_stale: bool) -> None:
    """Semantic search across memories."""
    from cerebrofy.memory.embedder import embed_memory
    from cerebrofy.memory.search import recall_memories

    root = Path.cwd()
    conn = _open(root)
    embedding = embed_memory(query, "")
    results = recall_memories(conn, embedding, limit=limit, type_filter=mem_type,
                              lobe_filter=lobe, include_stale=include_stale)
    conn.close()

    if not results:
        click.echo("No memories found.")
        return

    t = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    t.add_column("Score", justify="right")
    t.add_column("Type")
    t.add_column("Title")
    t.add_column("Lobe")
    t.add_column("Status")
    t.add_column("ID")
    for mem, score in results:
        t.add_row(f"{score:.3f}", mem.type, mem.title, mem.lobe or "", mem.status, mem.id[:8])
    console.print(t)


@mem_group.command("list")
@click.option("--neuron", default=None, help="Filter by neuron.")
@click.option("--lobe", default=None, help="Filter by lobe.")
@click.option("--type", "mem_type", default=None, help="Filter by type.")
@click.option("--include-stale", is_flag=True, default=False)
def memory_list(neuron: str | None, lobe: str | None, mem_type: str | None,
                include_stale: bool) -> None:
    """List memories for a neuron or lobe."""
    if not neuron and not lobe:
        click.echo("Error: provide --neuron or --lobe.", err=True)
        sys.exit(1)

    from cerebrofy.memory.store import list_memories

    root = Path.cwd()
    conn = _open(root)
    neuron_id: str | None = None
    if neuron:
        db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
        try:
            from cerebrofy.db.connection import open_db
            idx = open_db(db_path)
            rows = idx.execute(
                "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                (neuron, f"%::{neuron}"),
            ).fetchall()
            idx.close()
            if rows:
                if len(rows) > 1:
                    matches = ", ".join(r[0] for r in rows[:5])
                    click.echo(
                        f"Warning: '{neuron}' matches {len(rows)} neurons ({matches}…) — "
                        f"showing first match. Use file::name for precision.",
                        err=True,
                    )
                neuron_id = rows[0][0]
        except Exception:
            pass
    memories = list_memories(conn, neuron_id=neuron_id, lobe=lobe,
                             type_filter=mem_type, include_stale=include_stale)
    conn.close()

    if not memories:
        click.echo("No memories found.")
        return

    t = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    t.add_column("ID")
    t.add_column("Type")
    t.add_column("Title")
    t.add_column("Author")
    t.add_column("Status")
    t.add_column("Score", justify="right")
    for m in memories:
        t.add_row(m.id[:8], m.type, m.title, m.author or "", m.status, f"{m.decay_score:.2f}")
    console.print(t)


@mem_group.command("link")
@click.argument("from_id")
@click.argument("to_id")
@click.option("--rel", required=True,
              type=click.Choice(["caused", "motivated", "resolved", "contradicts", "updated_by"]),
              help="Relationship type.")
def memory_link(from_id: str, to_id: str, rel: str) -> None:
    """Create a causal link between two memories."""
    from cerebrofy.memory.store import MemoryEdge, write_memory_edge

    root = Path.cwd()
    conn = _open(root)
    edge = MemoryEdge(from_id, to_id, rel, int(time.time()), _get_author(None))
    write_memory_edge(conn, edge)
    conn.commit()
    conn.close()
    click.echo(f"Linked {from_id[:8]} --[{rel}]--> {to_id[:8]}")


@mem_group.command("export")
@click.option("--format", "fmt", default="markdown",
              type=click.Choice(["markdown", "json"]), show_default=True)
@click.option("--lobe", default=None, help="Filter by lobe.")
@click.option("--type", "mem_type", default=None, help="Filter by type.")
def memory_export(fmt: str, lobe: str | None, mem_type: str | None) -> None:
    """Export memories as markdown or JSON."""
    import datetime

    from cerebrofy.memory.store import list_memories

    root = Path.cwd()
    conn = _open(root)
    memories = list_memories(conn, lobe=lobe, type_filter=mem_type, include_stale=True)
    conn.close()

    if fmt == "json":
        out = [
            {
                "id": m.id, "type": m.type, "title": m.title, "body": m.body,
                "neuron_id": m.neuron_id, "lobe": m.lobe, "author": m.author,
                "created_ts": m.created_ts, "tags": list(m.tags),
                "decay_score": m.decay_score, "status": m.status,
            }
            for m in memories
        ]
        click.echo(json.dumps(out, indent=2))
    else:
        lines = ["# Cerebrofy Memory Export\n"]
        for m in memories:
            dt = datetime.datetime.fromtimestamp(m.created_ts).strftime("%Y-%m-%d")
            lines.append(f"## [{m.type}] {m.title}\n")
            lines.append(f"*by {m.author or 'unknown'} on {dt}*  ")
            if m.lobe:
                lines.append(f"*lobe: {m.lobe}*  ")
            if m.tags:
                lines.append(f"*tags: {', '.join(m.tags)}*  ")
            lines.append(f"*status: {m.status} (decay: {m.decay_score:.2f})*\n")
            lines.append(m.body + "\n")
        click.echo("\n".join(lines))
