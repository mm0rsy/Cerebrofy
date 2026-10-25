"""cerebrofy session — live agent session recorder CLI (Idea #11).

Recorded sessions are local-only (`.cerebrofy/db/sessions.db`) and opt-in via
`record_sessions: true` in `.cerebrofy/config.yaml`. Once a session has been
recorded, the read commands (`list`/`show`/`diff`/`search`/`export`) work
regardless of the flag.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import rich_click as click
from rich import box
from rich.console import Console
from rich.table import Table

from cerebrofy.session.recorder import (
    SessionEvent,
    SessionNotFoundError,
    SessionRecord,
    get_session,
    latest_session,
    list_events,
    list_sessions,
    neuron_blast_metric,
    open_sessions_db,
    search_sessions,
)
from cerebrofy.session.replay import SessionDiff, build_session_diff, session_to_dict
from cerebrofy.session.reporter import format_duration, format_utc, render_html, render_markdown

console = Console()


def _resolve_root() -> Path:
    """Resolve the repo root via the shared pure finder; exit the CLI on failure.

    The *finding* itself (walk-up for ``.cerebrofy/config.yaml``, honoring an
    explicit ``CEREBROFY_ROOT`` binding) is delegated to
    :func:`cerebrofy.utils.paths.require_repo_root`, which raises
    ``FileNotFoundError`` when no project is found. Only the user-facing
    message and exit code are handled here, in the CLI layer — this helper
    itself no longer performs any root resolution.
    """
    from cerebrofy.utils.paths import InvalidRepoRootError, require_repo_root

    try:
        return require_repo_root()
    except FileNotFoundError:
        click.echo("Error: Not initialized. Run 'cerebrofy init' first.", err=True)
        sys.exit(1)
    except InvalidRepoRootError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


def _open(root: Path) -> sqlite3.Connection:
    return open_sessions_db(root / ".cerebrofy")


def _index_conn(root: Path) -> sqlite3.Connection | None:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _no_sessions() -> None:
    click.echo(
        "No sessions recorded yet. Enable recording with 'record_sessions: true' "
        "in .cerebrofy/config.yaml, then call cerebrofy_session_start."
    )


def _resolve_session(conn: sqlite3.Connection, session_id: str | None) -> SessionRecord:
    session = get_session(conn, session_id) if session_id else latest_session(conn)
    if session is None:
        raise SessionNotFoundError(session_id or "<latest>")
    return session


def _load_replay(
    root: Path, session_id: str | None
) -> tuple[SessionRecord, list[SessionEvent], SessionDiff]:
    conn = _open(root)
    index_conn = _index_conn(root)
    try:
        session = _resolve_session(conn, session_id)
        events = list_events(conn, session.id)
        diff = build_session_diff(session, events, index_conn)
        return session, events, diff
    finally:
        conn.close()
        if index_conn is not None:
            index_conn.close()


def _session_brief(session: SessionRecord) -> dict[str, Any]:
    return {
        "session_id": session.id,
        "task": session.task,
        "agent": session.agent,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "duration_seconds": session.duration_seconds,
        "outcome": session.outcome,
        "event_count": session.event_count,
        "neurons_touched": len(session.neurons_touched),
        "blast_radius_before": session.blast_radius_before,
        "blast_radius_after": session.blast_radius_after,
    }


# ---------------------------------------------------------------------------
# cerebrofy session list
# ---------------------------------------------------------------------------

@click.group("session")
def session_group() -> None:
    """Record, replay, and audit AI agent sessions (opt-in, local-only)."""


@session_group.command("list")
@click.option("--limit", default=20, show_default=True, help="Maximum number of sessions.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def session_list(limit: int, fmt: str) -> None:
    """List recorded sessions, newest first."""
    root = _resolve_root()
    conn = _open(root)
    try:
        sessions = list_sessions(conn, limit=limit)
    finally:
        conn.close()

    if not sessions:
        _no_sessions()
        return

    if fmt == "json":
        click.echo(json.dumps([_session_brief(s) for s in sessions], indent=2))
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    table.add_column("Session", style="cyan")
    table.add_column("Started")
    table.add_column("Agent", style="dim")
    table.add_column("Task")
    table.add_column("Outcome")
    table.add_column("Events", justify="right")
    table.add_column("Duration", justify="right")
    for s in sessions:
        task = s.task if len(s.task) <= 48 else s.task[:47] + "…"
        outcome = s.outcome
        if s.is_active:
            outcome += " (open)"
        table.add_row(
            s.id,
            format_utc(s.started_at),
            s.agent or "—",
            task,
            outcome,
            str(s.event_count),
            format_duration(s.duration_seconds) if s.ended_at else "running",
        )
    console.print(table)
    console.print(f"[dim]{len(sessions)} session(s). Use 'cerebrofy session show <id>' for a replay.[/dim]")


# ---------------------------------------------------------------------------
# cerebrofy session show
# ---------------------------------------------------------------------------

@session_group.command("show")
@click.argument("session_id", required=False)
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]),
              default="markdown", show_default=True, help="Output format.")
def session_show(session_id: str | None, fmt: str) -> None:
    """Show the full replay of SESSION_ID (latest when omitted)."""
    root = _resolve_root()
    try:
        session, events, diff = _load_replay(root, session_id)
    except SessionNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if fmt == "json":
        click.echo(json.dumps(session_to_dict(session, events, diff), indent=2))
        return
    click.echo(render_markdown(session, events, diff))


# ---------------------------------------------------------------------------
# cerebrofy session diff
# ---------------------------------------------------------------------------

@session_group.command("diff")
@click.argument("session_id", required=False)
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def session_diff(session_id: str | None, fmt: str) -> None:
    """Show the graph changes made during SESSION_ID."""
    root = _resolve_root()
    try:
        session, _events, diff = _load_replay(root, session_id)
    except SessionNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    index_conn = _index_conn(root)
    try:
        callers_now: dict[str, int | None] = {
            node_id: neuron_blast_metric(index_conn, node_id) if index_conn else None
            for node_id in diff.touched
        }
    finally:
        if index_conn is not None:
            index_conn.close()

    if fmt == "json":
        payload = {
            "session_id": session.id,
            "task": session.task,
            "graph_refreshed": diff.graph_refreshed,
            "blast_radius_before": diff.blast_radius_before,
            "blast_radius_after": diff.blast_radius_after,
            "blast_radius_delta": diff.blast_delta,
            "verdict": diff.risk_verdict,
            "neurons": [
                {
                    "id": node_id,
                    "status": "missing" if node_id in diff.missing else "present",
                    "callers_now": callers_now.get(node_id),
                }
                for node_id in diff.touched
            ],
            "appeared": list(diff.appeared),
        }
        click.echo(json.dumps(payload, indent=2))
        return

    console.print()
    console.print(f"[bold]Graph changes — {session.id}[/bold]  [dim]({session.task})[/dim]")
    console.print()
    if diff.graph_refreshed:
        console.print("[yellow]Index was refreshed mid-session (build/update detected).[/yellow]")
    if not diff.touched:
        console.print("No neurons touched during this session.")
    else:
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
        table.add_column("Neuron", style="cyan")
        table.add_column("Node id", style="dim")
        table.add_column("Status")
        table.add_column("Callers (d2) now", justify="right")
        for node_id in diff.touched:
            status = "removed" if node_id in diff.missing else "present"
            callers = callers_now.get(node_id)
            table.add_row(
                node_id.rsplit("::", 1)[-1],
                node_id,
                f"[red]{status}[/red]" if status == "removed" else status,
                "—" if callers is None else str(callers),
            )
        console.print(table)
    if diff.appeared:
        console.print(
            "Appeared during session: "
            + ", ".join(n.rsplit("::", 1)[-1] for n in diff.appeared)
        )
    before = "—" if diff.blast_radius_before is None else str(diff.blast_radius_before)
    after = "—" if diff.blast_radius_after is None else str(diff.blast_radius_after)
    delta = diff.blast_delta
    delta_text = "" if delta is None else f" ({'+' if delta > 0 else ''}{delta})"
    console.print(
        f"Blast radius: {before} → {after}{delta_text} — verdict: [bold]{diff.risk_verdict}[/bold]"
    )
    console.print()


# ---------------------------------------------------------------------------
# cerebrofy session search
# ---------------------------------------------------------------------------

@session_group.command("search")
@click.argument("query")
@click.option("--limit", default=10, show_default=True, help="Maximum number of results.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True, help="Output format.")
def session_search(query: str, limit: int, fmt: str) -> None:
    """Semantic search across session tasks (falls back to task-text match)."""
    from cerebrofy.config.loader import load_config

    root = _resolve_root()
    config = load_config(root / ".cerebrofy" / "config.yaml")

    embedding: list[float] | None = None
    try:
        from cerebrofy.search.hybrid import embed_query

        embedding = embed_query(query, config.embedding_model)
    except Exception as exc:  # noqa: BLE001
        click.echo(
            f"Cerebrofy: semantic search unavailable ({exc}) — "
            f"falling back to task-text match.",
            err=True,
        )

    conn = _open(root)
    try:
        hits = search_sessions(conn, query, query_embedding=embedding, limit=limit)
    finally:
        conn.close()

    if not hits:
        click.echo("No matching sessions.")
        return

    if fmt == "json":
        click.echo(json.dumps(
            [
                {**_session_brief(hit.session), "score": hit.score, "match_kind": hit.match_kind}
                for hit in hits
            ],
            indent=2,
        ))
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    table.add_column("Score", justify="right")
    table.add_column("Session", style="cyan")
    table.add_column("Task")
    table.add_column("Outcome")
    table.add_column("Started")
    for hit in hits:
        score = f"{hit.score:.3f}" if hit.match_kind == "semantic" else "text"
        table.add_row(
            score,
            hit.session.id,
            hit.session.task,
            hit.session.outcome,
            format_utc(hit.session.started_at),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# cerebrofy session export
# ---------------------------------------------------------------------------

@session_group.command("export")
@click.argument("session_id", required=False)
@click.option("--format", "fmt", type=click.Choice(["html", "markdown", "json"]),
              default="html", show_default=True, help="Output format.")
@click.option("--output", "output_path", default=None, metavar="PATH",
              help="Write to this path instead of stdout.")
def session_export(session_id: str | None, fmt: str, output_path: str | None) -> None:
    """Export SESSION_ID as a shareable report (HTML, Markdown, or JSON)."""
    root = _resolve_root()
    try:
        session, events, diff = _load_replay(root, session_id)
    except SessionNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if fmt == "html":
        rendered = render_html(session, events, diff)
    elif fmt == "json":
        rendered = json.dumps(session_to_dict(session, events, diff), indent=2)
    else:
        rendered = render_markdown(session, events, diff)

    if output_path:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rendered, encoding="utf-8")
        click.echo(f"Wrote {dest}", err=True)
        return
    click.echo(rendered)


# ---------------------------------------------------------------------------
# cerebrofy session start
# ---------------------------------------------------------------------------

@session_group.command("start")
@click.argument("task")
@click.option("--agent-id", default=None, help="Acting agent id.")
@click.option("--agent-type", type=click.Choice(["claude", "cursor", "devin", "human", "ci"]), default="claude", help="Agent type.")
@click.option("--ttl-minutes", type=int, default=60, show_default=True, help="Claim lifetime before auto-release.")
def session_start(task: str, agent_id: str | None, agent_type: str, ttl_minutes: int) -> None:
    """Start recording a new session. Requires record_sessions: true in config.yaml."""
    from cerebrofy.mcp.tools.session import handle_session_start

    root = _resolve_root()

    # Check if recording is enabled
    from cerebrofy.config.loader import load_config
    config = load_config(root / ".cerebrofy" / "config.yaml")
    if not config.record_sessions:
        click.echo(
            "Error: session recording is disabled. Set 'record_sessions: true' "
            "in .cerebrofy/config.yaml and restart the MCP server.",
            err=True
        )
        sys.exit(1)

    from cerebrofy.mcp.tools.session import _recording_enabled
    if not _recording_enabled(root / ".cerebrofy" / "config.yaml"):
        click.echo(
            "Error: session recording is disabled. Set 'record_sessions: true' "
            "in .cerebrofy/config.yaml and restart the MCP server.",
            err=True
        )
        sys.exit(1)

    result = handle_session_start({
        "task": task,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "ttl_minutes": ttl_minutes,
    })
    click.echo(result[0].text)


# ---------------------------------------------------------------------------
# cerebrofy session end
# ---------------------------------------------------------------------------

@session_group.command("end")
@click.argument("session_id", required=False)
@click.option("--outcome", type=click.Choice(["success", "partial", "failed", "unknown"]), default="success", help="Session outcome.")
@click.option("--summary", default=None, help="Outcome notes.")
def session_end(session_id: str | None, outcome: str, summary: str | None) -> None:
    """Close a session and return its metrics."""
    from cerebrofy.mcp.tools.session import handle_session_end

    session_id_str = session_id if session_id else None

    result = handle_session_end({
        "session_id": session_id_str,
        "outcome": outcome,
        "summary": summary,
    })
    click.echo(result[0].text)


if __name__ == "__main__":
    session_group()
