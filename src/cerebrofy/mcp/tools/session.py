"""MCP handlers for the Live Agent Session Recorder (Idea #11).

Tools: ``cerebrofy_session_start``, ``cerebrofy_session_end``,
``cerebrofy_session_show``. Recording is opt-in (``record_sessions: true``) and
local-only — nothing is uploaded.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from cerebrofy.errors import NO_INDEX
from cerebrofy.mcp.errors import mcp_error as _err
from cerebrofy.session.recorder import (
    NO_ACTIVE_SESSION,
    RECORDING_DISABLED,
    SESSION_NOT_FOUND,
    SessionRecord,
    active_session,
    end_session,
    get_session,
    latest_session,
    list_events,
    list_sessions,
    open_sessions_db,
    search_sessions,
    start_session,
)
from cerebrofy.utils.paths import find_repo_root as _find_repo_root_impl


def _find_root(cwd: Path) -> Path:
    """Resolve the repo root from *cwd* (delegates to the shared helper).

    Honors an explicit ``--root``/``CEREBROFY_ROOT`` binding before walking up
    so a manipulated CWD cannot redirect the tool at another project.
    """
    root = _find_repo_root_impl(cwd)
    if root is None:
        raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")
    return root


def _recording_enabled(config_path: Path) -> bool:
    from cerebrofy.config.loader import load_config

    return bool(load_config(config_path).record_sessions)


def _embed_task(task: str, config_path: Path) -> list[float] | None:
    """Embed the task text for `session search`; None when unavailable."""
    try:
        from cerebrofy.config.loader import load_config
        from cerebrofy.search.hybrid import embed_query

        config = load_config(config_path)
        return embed_query(task, config.embedding_model)
    except Exception:  # noqa: BLE001
        return None


def _index_conn(cerebrofy_dir: Path) -> sqlite3.Connection | None:
    """Read-only cerebrofy.db connection, or None when there is no index."""
    db_path = cerebrofy_dir / "db" / "cerebrofy.db"
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _open_sessions(cerebrofy_dir: Path) -> sqlite3.Connection:
    return open_sessions_db(cerebrofy_dir)


# ---------------------------------------------------------------------------
# cerebrofy_session_start
# ---------------------------------------------------------------------------

def handle_session_start(arguments: dict[str, Any]) -> list[Any]:
    """Start recording a new session. Output: {"session_id": ..., ...}."""
    from mcp.types import TextContent

    task = str(arguments.get("task", "") or "").strip()
    if not task:
        return _err("[error] 'task' is required — describe the coding task being started.")

    try:
        root = _find_root(Path.cwd())
    except Exception:  # noqa: BLE001
        return _err(f"[{NO_INDEX}] could not find .cerebrofy directory. Run 'cerebrofy init' first.")

    config_path = root / ".cerebrofy" / "config.yaml"
    if not _recording_enabled(config_path):
        return _err(
            f"[{RECORDING_DISABLED}] session recording is opt-in. Set "
            "'record_sessions: true' in .cerebrofy/config.yaml and restart the "
            "MCP server."
        )

    agent = arguments.get("agent")
    agent_str = str(agent).strip() if agent else None
    embedding = _embed_task(task, config_path)

    conn = _open_sessions(Path(root / ".cerebrofy"))
    try:
        session = start_session(conn, task=task, agent=agent_str, embedding=embedding)
        others = [s.id for s in list_sessions(conn, limit=5) if s.is_active and s.id != session.id]
    finally:
        conn.close()

    out: dict[str, Any] = {
        "session_id": session.id,
        "task": session.task,
        "agent": session.agent,
        "started_at": session.started_at,
        "recording": True,
    }
    if others:
        out["warning"] = (
            f"{len(others)} other session(s) still open: {', '.join(others)}. "
            f"Tool calls are recorded into the most recent open session."
        )
    return [TextContent(type="text", text=json.dumps(out, indent=2))]


# ---------------------------------------------------------------------------
# cerebrofy_session_end
# ---------------------------------------------------------------------------

def handle_session_end(arguments: dict[str, Any]) -> list[Any]:
    """Close a session and return its metrics."""
    from mcp.types import TextContent

    session_id = str(arguments.get("session_id", "") or "").strip()
    if not session_id:
        return _err("[error] 'session_id' is required.")

    try:
        root = _find_root(Path.cwd())
    except Exception:  # noqa: BLE001
        return _err(f"[{NO_INDEX}] could not find .cerebrofy directory. Run 'cerebrofy init' first.")

    cerebrofy_dir = root / ".cerebrofy"
    outcome = arguments.get("outcome")
    summary = arguments.get("summary")

    conn = _open_sessions(cerebrofy_dir)
    index_conn = _index_conn(cerebrofy_dir)
    try:
        existing = get_session(conn, session_id)
        if existing is None:
            return _err(
                f"[{SESSION_NOT_FOUND}] no session with id '{session_id}'. "
                f"Use cerebrofy_session_show to list recent sessions."
            )
        if not existing.is_active:
            return _err(
                f"[{NO_ACTIVE_SESSION}] session '{session_id}' already ended "
                f"at {existing.ended_at}. Call cerebrofy_session_start to begin a new one."
            )
        try:
            session = end_session(
                conn,
                session_id,
                outcome=str(outcome) if outcome else None,
                notes=str(summary) if summary else None,
                index_conn=index_conn,
                cerebrofy_dir=cerebrofy_dir,
            )
        except ValueError as exc:
            return _err(f"[error] {exc}")
    except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
        return _err(f"cerebrofy_session_end failed: {exc}")
    finally:
        conn.close()
        if index_conn is not None:
            index_conn.close()

    out: dict[str, Any] = {
        "session_id": session.id,
        "duration_seconds": session.duration_seconds,
        "neurons_touched": len(session.neurons_touched),
        "events_recorded": session.event_count,
        "outcome": session.outcome,
        "blast_radius_before": session.blast_radius_before,
        "blast_radius_after": session.blast_radius_after,
    }
    return [TextContent(type="text", text=json.dumps(out, indent=2))]


# ---------------------------------------------------------------------------
# cerebrofy_session_show
# ---------------------------------------------------------------------------

def handle_session_show(arguments: dict[str, Any]) -> list[Any]:
    """Return the full replay of a session (latest when no id is given)."""
    from mcp.types import TextContent

    session_id = arguments.get("session_id")
    session_id_str = str(session_id).strip() if session_id else None
    fmt = str(arguments.get("format", "markdown") or "markdown").lower()
    if fmt not in ("markdown", "json"):
        return _err("[error] 'format' must be 'markdown' or 'json'.")

    try:
        root = _find_root(Path.cwd())
    except Exception:  # noqa: BLE001
        return _err(f"[{NO_INDEX}] could not find .cerebrofy directory. Run 'cerebrofy init' first.")

    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "sessions.db").exists():
        return _err(
            f"[{SESSION_NOT_FOUND}] no sessions recorded yet. Enable recording with "
            f"'record_sessions: true' in .cerebrofy/config.yaml, then call "
            f"cerebrofy_session_start."
        )

    conn = _open_sessions(cerebrofy_dir)
    index_conn = _index_conn(cerebrofy_dir)
    try:
        session: SessionRecord | None = (
            get_session(conn, session_id_str) if session_id_str else latest_session(conn)
        )
        if session is None:
            raise LookupError(session_id_str or "<latest>")

        from cerebrofy.session.replay import build_session_diff, session_to_dict

        events = list_events(conn, session.id)
        diff = build_session_diff(session, events, index_conn)
        if fmt == "json":
            return [TextContent(
                type="text", text=json.dumps(session_to_dict(session, events, diff), indent=2)
            )]

        from cerebrofy.session.reporter import render_markdown

        return [TextContent(type="text", text=render_markdown(session, events, diff))]
    except LookupError:
        return _err(f"[{SESSION_NOT_FOUND}] no session with id '{session_id_str or '<latest>'}'.")
    except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
        return _err(f"cerebrofy_session_show failed: {exc}")
    finally:
        conn.close()
        if index_conn is not None:
            index_conn.close()


# ---------------------------------------------------------------------------
# cerebrofy_session_search
# ---------------------------------------------------------------------------

def handle_session_search(arguments: dict[str, Any]) -> list[Any]:
    """Semantic search across session tasks (falls back to task-text match)."""
    from mcp.types import TextContent

    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return _err("[error] 'query' is required.")

    limit = int(arguments.get("limit", 10))

    try:
        root = _find_root(Path.cwd())
    except Exception:  # noqa: BLE001
        return _err(f"[{NO_INDEX}] could not find .cerebrofy directory. Run 'cerebrofy init' first.")

    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "sessions.db").exists():
        return _err(
            f"[{SESSION_NOT_FOUND}] no sessions recorded yet. Enable recording with "
            f"'record_sessions: true' in .cerebrofy/config.yaml, then call "
            f"cerebrofy_session_start."
        )

    config_path = root / ".cerebrofy" / "config.yaml"
    embedding: list[float] | None = None
    try:
        from cerebrofy.config.loader import load_config
        from cerebrofy.search.hybrid import embed_query
        config = load_config(config_path)
        embedding = embed_query(query, config.embedding_model)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")

    conn = _open_sessions(cerebrofy_dir)
    try:
        hits = search_sessions(conn, query, query_embedding=embedding, limit=limit)
    finally:
        conn.close()

    if not hits:
        return [TextContent(type="text", text=json.dumps({"hits": [], "count": 0}, indent=2))]

    results = []
    for hit in hits:
        results.append({
            "session_id": hit.session.id,
            "task": hit.session.task,
            "outcome": hit.session.outcome,
            "started_at": hit.session.started_at,
            "score": hit.score,
            "match_kind": hit.match_kind,
        })

    return [TextContent(type="text", text=json.dumps({"hits": results, "count": len(results)}, indent=2))]


# ---------------------------------------------------------------------------
# cerebrofy_session_export
# ---------------------------------------------------------------------------

def handle_session_export(arguments: dict[str, Any]) -> list[Any]:
    """Export a session as a shareable report (HTML, Markdown, or JSON)."""
    from mcp.types import TextContent

    session_id = arguments.get("session_id")
    session_id_str = str(session_id).strip() if session_id else None
    fmt = str(arguments.get("format", "markdown") or "markdown").lower()
    if fmt not in ("html", "markdown", "json"):
        return _err("[error] 'format' must be 'html', 'markdown', or 'json'.")

    try:
        root = _find_root(Path.cwd())
    except Exception:  # noqa: BLE001
        return _err(f"[{NO_INDEX}] could not find .cerebrofy directory. Run 'cerebrofy init' first.")

    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "sessions.db").exists():
        return _err(
            f"[{SESSION_NOT_FOUND}] no sessions recorded yet. Enable recording with "
            f"'record_sessions: true' in .cerebrofy/config.yaml, then call "
            f"cerebrofy_session_start."
        )

    conn = _open_sessions(cerebrofy_dir)
    index_conn = _index_conn(cerebrofy_dir)
    try:
        session: SessionRecord | None = (
            get_session(conn, session_id_str) if session_id_str else latest_session(conn)
        )
        if session is None:
            raise LookupError(session_id_str or "<latest>")

        from cerebrofy.session.replay import build_session_diff, session_to_dict
        from cerebrofy.session.reporter import render_html, render_markdown

        events = list_events(conn, session.id)
        diff = build_session_diff(session, events, index_conn)

        if fmt == "json":
            content = json.dumps(session_to_dict(session, events, diff), indent=2)
        elif fmt == "html":
            content = render_html(session, events, diff)
        else:
            content = render_markdown(session, events, diff)

        return [TextContent(type="text", text=content)]
    except LookupError:
        return _err(f"[{SESSION_NOT_FOUND}] no session with id '{session_id_str or '<latest>'}'.")
    except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
        return _err(f"cerebrofy_session_export failed: {exc}")
    finally:
        conn.close()
        if index_conn is not None:
            index_conn.close()


def active_session_id(cerebrofy_dir: Path) -> str | None:
    """Return the id of the currently active session, or None (CLI helper)."""
    conn = open_sessions_db(cerebrofy_dir)
    try:
        session = active_session(conn)
        return session.id if session else None
    finally:
        conn.close()
