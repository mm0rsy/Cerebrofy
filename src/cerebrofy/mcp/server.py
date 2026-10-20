"""MCP stdio server for cerebrofy.

Exposes the full tool surface — semantic search, blast radius, context
packing, memory, health, onboarding, and more — plus URI-addressable MCP
*resources* for ambient navigation context (codebase map, entry points,
lobes, neurons, memories, blast radius).

Resources are discoverable via the ``cerebrofy_list_resources`` tool and
support client subscriptions: when ``cerebrofy build``/``update`` modifies the
index, the server emits ``notifications/resources/updated`` for subscribed
URIs so clients never work with stale graph data.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import os
import sys
from pathlib import Path
from typing import Any, Callable

from mcp import types as mcp_types
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from pydantic import AnyUrl

from cerebrofy.mcp.tool_specs import SPEC_BY_NAME, TOOL_SPECS
from cerebrofy.mcp.tools.changelog import handle_changelog as _handle_changelog
from cerebrofy.mcp.tools.governance import handle_governance as _handle_governance
from cerebrofy.mcp.tools.memory_graph import handle_link_memories as _handle_link_memories
from cerebrofy.mcp.tools.memory_graph import handle_trace_history as _handle_trace_history
from cerebrofy.mcp.tools.onboard import handle_onboard as _handle_onboard
from cerebrofy.mcp.tools.session import handle_session_end as _handle_session_end
from cerebrofy.mcp.tools.session import handle_session_show as _handle_session_show
from cerebrofy.mcp.tools.session import handle_session_start as _handle_session_start
from cerebrofy.mcp.tools.plan import handle_plan as _handle_plan
from cerebrofy.mcp.tools.review import handle_review as _handle_review
from cerebrofy.mcp.tools.upgrade import handle_upgrade as _handle_upgrade
from cerebrofy.utils.paths import (
    InvalidRepoRootError,
    find_repo_root,
    require_repo_root,
    set_bound_root,
    set_root_boundary,
)
from cerebrofy.errors import NO_INDEX
from cerebrofy.constants import DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Server subclass — advertise resource subscription support
# ---------------------------------------------------------------------------

# The base degrades to Any when mypy runs without the optional mcp extra.
class CerebrofyMCPServer(Server):  # type: ignore[type-arg, misc]
    """MCP server that advertises resource subscriptions once wired.

    The mcp SDK (1.x) hard-codes ``subscribe=False`` in the resources
    capability even when ``@subscribe_resource`` handlers are registered (the
    2.x SDK derives it from registered handlers). This subclass flips the flag
    back on when our subscribe handler is present, so well-behaved clients
    know they can subscribe to ``notifications/resources/updated``.
    """

    def get_capabilities(
        self,
        notification_options: NotificationOptions,
        experimental_capabilities: dict[str, dict[str, Any]],
    ) -> Any:
        caps = super().get_capabilities(notification_options, experimental_capabilities)
        if caps.resources is not None and mcp_types.SubscribeRequest in self.request_handlers:
            caps.resources.subscribe = True
        return caps


# ---------------------------------------------------------------------------
# Resource subscription plumbing
# ---------------------------------------------------------------------------

# Fingerprint poll interval (seconds). Worst-case notification latency after
# `cerebrofy update` is one interval; 0.5s keeps it under the <1s target from
# idea #10 — the fingerprint itself is only three stat/glob calls.
_INDEX_WATCH_INTERVAL_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Server-side caps on user-supplied integers (Idea #25 / DoS hardening).
#
# The tool JSON schemas advertise ``maximum`` bounds, but a non-compliant or
# malicious client can ignore them. We enforce hard caps here too so a huge
# ``top_k``/``limit``/``top`` cannot exhaust memory or CPU, and malformed values
# produce a clean MCP error instead of an uncaught ``ValueError``/``TypeError``.
# ---------------------------------------------------------------------------
_MAX_TOP_K = 50      # matches search_code schema maximum
_MAX_LIMIT = 100     # cerebrofy_recall result limit
_MAX_RESULT_TOP = 100  # cerebrofy_silo / coverage_gap "top N" rankings


def _parse_int_arg(
    arguments: dict[str, Any],
    key: str,
    default: int,
    *,
    maximum: int,
    minimum: int = 1,
) -> tuple[int, str | None]:
    """Validate, clamp, and return an integer tool argument.

    Returns ``(value, None)`` on success or ``(0, message)`` when *value* is not
    a valid integer. Out-of-range values are clamped to ``[minimum, maximum]``
    rather than rejected, matching the permissive intent of the schemas.
    """
    raw = arguments.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0, f"[error] '{key}' must be an integer, got {raw!r}."
    if value < minimum:
        value = minimum
    elif value > maximum:
        value = maximum
    return value, None


async def _notify_resource_changes(
    session: Any,
    subscriptions: set[str],
    *,
    db_changed: bool,
    docs_changed: bool,
) -> None:
    """Emit change notifications for subscribed resources.

    ``resources/updated`` is sent per subscribed URI whenever the index or the
    generated docs changed; ``resources/list_changed`` is sent when lobe
    Markdown files changed (the resource list may have gained/lost entries).
    """
    if db_changed or docs_changed:
        for uri in sorted(subscriptions):
            await session.send_resource_updated(AnyUrl(uri))
    if docs_changed:
        await session.send_resource_list_changed()


async def _watch_index_changes(session: Any, subscriptions: set[str], root: Path) -> None:
    """Poll the index fingerprint and notify the client when it changes."""
    from cerebrofy.mcp.resources import index_fingerprint

    previous = index_fingerprint(root)
    while True:
        await asyncio.sleep(_INDEX_WATCH_INTERVAL_SECONDS)
        current = index_fingerprint(root)
        if current == previous:
            continue
        db_changed = current[0] != previous[0] or current[1] != previous[1]
        docs_changed = current[2] != previous[2]
        previous = current
        try:
            await _notify_resource_changes(
                session, subscriptions, db_changed=db_changed, docs_changed=docs_changed
            )
        except Exception:
            return  # write failed — client connection is gone; stop quietly


def _start_index_watcher(app: Any, subscriptions: set[str], state: dict[str, Any]) -> None:
    """Start the background index watcher once, capturing the active session.

    Called from request handlers (any request proves a session exists). Safe
    to call repeatedly — only the first successful call starts the task.
    """
    if state.get("started"):
        return
    try:
        session = app.request_context.session
    except LookupError:
        return
    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError:
        return
    state["started"] = True
    task = asyncio.create_task(_watch_index_changes(session, subscriptions, root))
    state["task"] = task

    def _reset(_t: Any) -> None:
        state["started"] = False
        state["task"] = None

    task.add_done_callback(_reset)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Repo-root resolution now lives in ``cerebrofy.utils.paths`` (``find_repo_root``
# / ``require_repo_root``) so every tool command and the MCP server share one
# implementation. The MCP server pins the root at start-up only when an explicit
# root is supplied (``--root`` / ``CEREBROFY_ROOT``); otherwise handlers keep the
# documented per-call CWD routing. An explicit binding makes a manipulated CWD
# unable to redirect the server at a different project's databases.


def _run_cerebrofy(args: list[str], cwd: str, timeout: int = DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS) -> tuple[int, str]:
    """Run ``python -m cerebrofy <args>`` in *cwd*. Returns (returncode, output)."""
    result = subprocess.run(
        [sys.executable, "-m", "cerebrofy"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    stderr = result.stderr.strip()
    output = result.stdout + (("\n" + stderr) if stderr else "")
    return result.returncode, output.strip()


def _make_error_content(message: str) -> list[Any]:
    """Build a single-element ``TextContent`` error payload.

    Delegates to the shared :func:`cerebrofy.mcp.errors.mcp_error` so there is
    one canonical constructor for MCP error responses. The ``_make_error_content``
    name is retained for backwards compatibility with existing call sites.
    """
    from cerebrofy.mcp.errors import mcp_error

    return mcp_error(message)


def _open_db_ro(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        raise FileNotFoundError(
            "Index not found. Run 'cerebrofy build' first."
        )
    integrity_check = "warn"
    try:
        from cerebrofy.config.loader import load_config

        integrity_check = load_config(
            root / ".cerebrofy" / "config.yaml"
        ).database.integrity_check
    except Exception:  # config problems surface with their own errors elsewhere
        pass
    from cerebrofy.db.integrity import verify_integrity

    verify_integrity(db_path, integrity_check)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _record_session_event(
    name: str, arguments: dict[str, Any], result: list[Any]
) -> None:
    """Lend the dispatched tool call to the session recorder (Idea #11).

    Thin by design: all logic lives in ``cerebrofy.session.middleware`` and is a
    no-op unless opt-in recording is enabled and a session is active. Never raises.

    A per-request ``SessionMiddleware`` instance is created so there is no shared
    global state between concurrent tool-call threads.
    """
    try:
        from cerebrofy.session.middleware import SessionMiddleware, find_repo_root

        root = find_repo_root(Path.cwd())
        if root is None:
            return

        middleware = SessionMiddleware(root)
        try:
            middleware.record(name, arguments, result)
        finally:
            middleware.close()
    except Exception:
        return


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _handle_search_code(arguments: dict[str, Any]) -> list[Any]:
    """Hybrid semantic + keyword search — primary navigation tool."""
    from mcp.types import TextContent

    query: str = arguments.get("query", "")
    top_k, _err = _parse_int_arg(arguments, "top_k", 10, maximum=_MAX_TOP_K)
    if _err is not None:
        return _make_error_content(_err)
    lobe_filter: str | None = arguments.get("lobe")

    if not query:
        return _make_error_content("[error] 'query' is required.")

    root = require_repo_root(Path.cwd())
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _make_error_content("Index not found. Run 'cerebrofy build' first.")

    from cerebrofy.config.loader import load_config
    from cerebrofy.search.hybrid import HybridSearchResult, embed_query, hybrid_search

    config = load_config(root / ".cerebrofy" / "config.yaml")

    try:
        embedding = embed_query(query, config.embedding_model)
    except ValueError as exc:
        return _make_error_content(f"[error] {exc}")

    result: HybridSearchResult = hybrid_search(
        query=query,
        db_path=db_path,
        embedding=embedding,
        top_k=top_k,
        lobes=config.lobes,
        repo_root=root,
    )

    neurons = result.matched_neurons
    if lobe_filter:
        neurons = [n for n in neurons if lobe_filter.lower() in (n.file or "").lower()]

    if not neurons:
        return [TextContent(type="text", text=json.dumps({"results": [], "count": 0}))]

    hits = [
        {
            "name": n.name,
            "type": n.type,
            "file": n.file,
            "line": n.line_start,
            "similarity": n.similarity,
            "summary": (n.docstring or n.signature or "")[:200],
        }
        for n in neurons
    ]
    return [TextContent(type="text", text=json.dumps({"results": hits, "count": len(hits)}, indent=2))]


def _handle_get_neuron(arguments: dict[str, Any]) -> list[Any]:
    """Fetch a single Neuron by name, or by file + optional line number."""
    from mcp.types import TextContent

    name: str | None = arguments.get("name")
    file: str | None = arguments.get("file")
    line: int | None = arguments.get("line")

    if not name and not file:
        return _make_error_content("[error] Provide 'name' or 'file'.")

    root = require_repo_root(Path.cwd())
    conn = _open_db_ro(root)
    try:
        if name:
            rows = conn.execute(
                "SELECT id, name, type, file, line_start, line_end, signature, docstring "
                "FROM nodes WHERE name = ? LIMIT 5",
                (name,),
            ).fetchall()
        else:
            q = (
                "SELECT id, name, type, file, line_start, line_end, signature, docstring "
                "FROM nodes WHERE file LIKE ?"
            )
            params: list[Any] = [f"%{file}%"]
            if line is not None:
                q += " AND line_start <= ? AND line_end >= ?"
                params += [line, line]
            rows = conn.execute(q, params).fetchmany(5)
    finally:
        conn.close()

    if not rows:
        return [TextContent(type="text", text=json.dumps({"neurons": [], "message": "Not found."}))]

    cols = ("id", "name", "type", "file", "line_start", "line_end", "signature", "docstring")
    neurons = [dict(zip(cols, row)) for row in rows]

    # Attach memories from memories.db (if it exists)
    try:
        from cerebrofy.memory.store import list_memories, open_memories_db
        cerebrofy_dir = root / ".cerebrofy"
        if (cerebrofy_dir / "db" / "memories.db").exists():
            mem_conn = open_memories_db(cerebrofy_dir)
            try:
                for result in neurons:
                    attached = list_memories(mem_conn, neuron_id=result.get("id"), include_stale=False)
                    result["memories"] = [
                        {
                            "id": m.id, "type": m.type, "title": m.title,
                            "body": m.body, "decay_score": m.decay_score,
                            "status": m.status, "tags": list(m.tags),
                        }
                        for m in attached
                    ]
            finally:
                mem_conn.close()
        else:
            for result in neurons:
                result["memories"] = []
    except Exception:
        for result in neurons:
            result.setdefault("memories", [])

    return [TextContent(type="text", text=json.dumps({"neurons": neurons}, indent=2))]


def _handle_list_lobes(arguments: dict[str, Any]) -> list[Any]:
    """Return available lobes by scanning the lobes markdown directory."""
    from mcp.types import TextContent

    root = require_repo_root(Path.cwd())
    lobes_dir = root / "docs" / "cerebrofy"
    map_file = root / "docs" / "cerebrofy" / "cerebrofy_map.md"

    lobes = []
    if lobes_dir.exists():
        for md_file in sorted(lobes_dir.glob("*_lobe.md")):
            lobe_name = md_file.stem.removesuffix("_lobe")
            lobes.append({
                "name": lobe_name,
                "summary_file": str(md_file.relative_to(root)),
            })

    return [TextContent(type="text", text=json.dumps({
        "lobes": lobes,
        "full_map": str(map_file.relative_to(root)) if map_file.exists() else None,
    }, indent=2))]


def _handle_list_resources(arguments: dict[str, Any]) -> list[Any]:
    """Return the catalog of available MCP resources (optionally filtered)."""
    from mcp.types import TextContent

    filter_value: str = arguments.get("filter", "all") or "all"

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[NO_INDEX] {exc}")

    from cerebrofy.mcp.resources import filter_resource_entries, list_resource_entries

    try:
        entries = filter_resource_entries(list_resource_entries(root), filter_value)
    except ValueError as exc:
        return _make_error_content(f"[error] {exc}")

    return [TextContent(type="text", text=json.dumps(
        {"resources": entries, "count": len(entries)}, indent=2
    ))]


def _handle_context(arguments: dict[str, Any]) -> list[Any]:
    """Budget-aware context window optimizer."""
    from mcp.types import TextContent

    task: str = arguments.get("task", "")
    if not task:
        return _make_error_content("[error] 'task' is required.")

    budget: int = int(arguments.get("budget", 8000))
    model: str = arguments.get("model", "auto")
    fmt: str = arguments.get("format", "json")

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _make_error_content("[NO_INDEX] Index not found. Run 'cerebrofy build' first.")

    try:
        from cerebrofy.context.exporter import to_claude_xml, to_json, to_markdown
        from cerebrofy.context.optimizer import optimize_context

        plan = optimize_context(
            task=task,
            db_path=db_path,
            config_path=root / ".cerebrofy" / "config.yaml",
            budget=budget,
            model=model,
            repo_root=root,
        )
    except ValueError as exc:
        return _make_error_content(f"[error] {exc}")

    if fmt == "markdown":
        return [TextContent(type="text", text=to_markdown(plan))]
    if fmt == "claude-xml":
        return [TextContent(type="text", text=to_claude_xml(plan))]
    return [TextContent(type="text", text=to_json(plan))]


def _handle_blast_radius(arguments: dict[str, Any]) -> list[Any]:
    """Blast radius for a single neuron target."""
    from mcp.types import TextContent

    target: str = arguments.get("target", "")
    if not target:
        return _make_error_content("[error] 'target' is required.")

    depth: int = int(arguments.get("depth", 2))
    fmt: str = arguments.get("format", "json")

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    conn = _open_db_ro(root)
    try:
        from cerebrofy.db.connection import check_schema_version
        from cerebrofy.mcp.resources import blast_radius_summary

        try:
            check_schema_version(conn)
        except ValueError as exc:
            return _make_error_content(f"Schema version mismatch: {exc}. Run 'cerebrofy migrate'.")

        payload = blast_radius_summary(target, conn, depth=depth)
    finally:
        conn.close()

    if payload is None:
        return _make_error_content(
            f"[NEURON_NOT_FOUND] Neuron '{target}' not found. Run 'cerebrofy build' first."
        )

    if fmt == "markdown":
        return [TextContent(type="text", text=str(payload["summary"]))]

    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


def _compute_epistemic(root: Path) -> "Any | None":
    """Return EpistemicState or None if the DB is unavailable."""
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return None
    try:
        from cerebrofy.config.loader import load_config
        from cerebrofy.db.connection import open_db
        from cerebrofy.epistemic.state import compute_epistemic_state

        config = load_config(root / ".cerebrofy" / "config.yaml")
        conn = open_db(db_path)
        try:
            return compute_epistemic_state(conn, config.tracked_extensions, root)
        finally:
            conn.close()
    except Exception:
        return None


def _with_epistemic(result: list[Any], root: Path) -> list[Any]:
    """Post-process a tool result list by injecting epistemic state into each TextContent."""
    from mcp.types import TextContent

    state = _compute_epistemic(root)
    if state is None:
        return result

    from cerebrofy.epistemic.state import inject_epistemic

    out = []
    for item in result:
        if isinstance(item, TextContent):
            out.append(TextContent(type="text", text=inject_epistemic(item.text, state)))
        else:
            out.append(item)
    return out


def _handle_epistemic(arguments: dict[str, Any]) -> list[Any]:
    """Return the current epistemic state as JSON or human-readable text."""
    from mcp.types import TextContent

    fmt: str = arguments.get("format", "json")

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _make_error_content("[NO_INDEX] Index not found. Run 'cerebrofy build' first.")

    state = _compute_epistemic(root)
    if state is None:
        return _make_error_content("[error] Could not compute epistemic state.")

    import json as _json
    if fmt == "human":
        pct = int(state.overall_confidence * 100)
        lines = [
            f"Epistemic Confidence: {pct}%",
            f"Graph age: {state.graph_age_hours:.1f}h",
            f"Neurons changed: {state.neurons_changed_since_build}",
        ]
        for c in state.caveats:
            lines.append(f"⚠️  {c}")
        lines.append(f"Recommendation: {state.recommendation}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=_json.dumps(state.to_dict(), indent=2))]


def _arch_history_summary(root: Path) -> "Any | None":
    """Arch check history summary for health output (Idea #16 × #03), or None."""
    try:
        from cerebrofy.arch.history import read_history, summarize_history

        entries = read_history(root)
        return summarize_history(entries) if entries else None
    except Exception:
        return None


def _handle_health(arguments: dict[str, Any]) -> list[Any]:
    """Return current health snapshot with delta from previous build."""
    from mcp.types import TextContent

    since_build: int = int(arguments.get("since_build", 1))
    metric: str = arguments.get("metric", "all")
    fmt: str = arguments.get("format", "markdown")

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _make_error_content("[NO_INDEX] Index not found. Run 'cerebrofy build' first.")

    try:
        from cerebrofy.config.loader import load_config
        from cerebrofy.db.connection import open_db
        from cerebrofy.health.metrics import compute_metrics
        from cerebrofy.health.reporter import format_health_snapshot, to_export_json
        from cerebrofy.health.snapshot import fetch_snapshots

        config = load_config(root / ".cerebrofy" / "config.yaml")
        conn = open_db(db_path)
        try:
            snapshots = fetch_snapshots(conn, limit=since_build + 1)
            metrics = compute_metrics(conn, config.lobes, prior_snapshots=snapshots)
        finally:
            conn.close()

        prev = snapshots[since_build - 1] if len(snapshots) >= since_build else None
        latest = snapshots[0] if snapshots else None
        ts = latest["build_ts"] if latest else None
        commit = latest.get("commit_hash") if latest else None
        arch_summary = _arch_history_summary(root)

        if fmt == "json":
            text = to_export_json(metrics, prev, ts, commit, arch_summary=arch_summary)
        else:
            text = format_health_snapshot(metrics, prev, ts, commit)
            if arch_summary is not None:
                from cerebrofy.health.reporter import format_arch_section

                text = text.rstrip("\n") + "\n" + format_arch_section(arch_summary)

        if metric != "all":
            val = getattr(metrics, metric, None)
            if val is None:
                return _make_error_content(f"[error] Unknown metric: {metric}")
            text = f"{metric}: {val}"

    except Exception as exc:
        return _make_error_content(f"[error] {exc}")

    return [TextContent(type="text", text=text)]


def _load_intent(root: Path) -> "Any | None":
    """Return IntentConfig or None if intent.yaml is missing or unreadable."""
    try:
        from cerebrofy.intent.loader import load_intent
        return load_intent(root / ".cerebrofy")
    except Exception:
        return None


def _with_intent(result: list[Any], root: Path) -> list[Any]:
    """Post-process a tool result list by injecting compact intent summary into each TextContent."""
    from mcp.types import TextContent

    intent = _load_intent(root)
    if intent is None:
        return result

    from cerebrofy.intent.enricher import inject_intent

    out = []
    for item in result:
        if isinstance(item, TextContent):
            out.append(TextContent(type="text", text=inject_intent(item.text, intent)))
        else:
            out.append(item)
    return out


def _handle_intent(arguments: dict[str, Any]) -> list[Any]:
    """Return current product intent, optionally filtered by lobe or neuron."""
    import json as _json
    from mcp.types import TextContent

    lobe: str | None = arguments.get("lobe")
    neuron: str | None = arguments.get("neuron")
    fmt: str = arguments.get("format", "json")

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    intent = _load_intent(root)
    if intent is None:
        return [TextContent(type="text", text=_json.dumps({
            "error": "NO_INTENT_FILE",
            "message": ".cerebrofy/intent.yaml not found. Run 'cerebrofy intent init' to create one.",
        }, indent=2))]

    output = intent.to_dict()

    # Compute relevance when a lobe or neuron filter is provided
    if lobe or neuron:
        from cerebrofy.intent.enricher import enrich_with_intent
        affected = [lobe] if lobe else []
        if neuron:
            # Extract lobe name from neuron path (first path component after src/)
            parts = neuron.replace("\\", "/").split("/")
            for part in parts:
                if part and part not in ("src", "cerebrofy", "tests"):
                    affected.append(part)
                    break
        relevance = enrich_with_intent(affected, intent)
        output["relevance_to_query"] = relevance
    else:
        output["relevance_to_query"] = None

    if fmt == "human":
        lines = []
        if intent.sprint:
            lines.append(f"Sprint: {intent.sprint.name} — {intent.sprint.goal}")
            lines.append(f"Deadline: {intent.sprint.deadline}")
            if intent.sprint.priority_lobes:
                lines.append(f"Priority lobes: {', '.join(intent.sprint.priority_lobes)}")
        if intent.incidents:
            lines.append(f"\nActive incidents: {len(intent.incidents)}")
            for inc in intent.incidents:
                lines.append(f"  [{inc.id}] {inc.description} ({inc.severity}/{inc.status})")
        if intent.architecture:
            lines.append(f"\nArchitectural direction: {intent.architecture.direction}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=_json.dumps(output, indent=2))]


def _handle_remember(arguments: dict[str, Any]) -> list[Any]:
    import json as _json
    import time as _time
    import uuid as _uuid

    title = arguments.get("title", "").strip()
    body = arguments.get("body", "").strip()
    mem_type = arguments.get("type", "").strip()

    if not title or not body or not mem_type:
        return _make_error_content("cerebrofy_remember: 'title', 'body', and 'type' are required")

    from cerebrofy.memory.store import VALID_TYPES
    if mem_type not in VALID_TYPES:
        return _make_error_content(
            f"cerebrofy_remember: invalid type '{mem_type}'. "
            f"Valid: {', '.join(sorted(VALID_TYPES))}"
        )

    try:
        root = require_repo_root(Path.cwd())
    except Exception:
        return _make_error_content(f"[{NO_INDEX}] could not find .cerebrofy directory")

    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db").exists():
        return _make_error_content(f"[{NO_INDEX}] run cerebrofy build first")

    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.store import Memory, open_memories_db, write_memory

        neuron_param = arguments.get("neuron")
        neuron_id: str | None = None
        warning_msg: str | None = None
        if neuron_param:
            db_path = cerebrofy_dir / "db" / "cerebrofy.db"
            try:
                from cerebrofy.db.connection import open_db
                idx = open_db(db_path)
                rows = idx.execute(
                    "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                    (neuron_param, f"%::{neuron_param}"),
                ).fetchall()
                idx.close()
                if not rows:
                    warning_msg = f"neuron '{neuron_param}' not found — memory stored without anchor"
                elif len(rows) > 1:
                    matches = ", ".join(r[0] for r in rows[:5])
                    warning_msg = (
                        f"'{neuron_param}' matches {len(rows)} neurons ({matches}…) — "
                        f"using first match. Use file::name for precision."
                    )
                    neuron_id = rows[0][0]
                else:
                    neuron_id = rows[0][0]
            except Exception:
                warning_msg = "could not resolve neuron — memory stored without anchor"

        tags_raw = arguments.get("tags", [])
        if isinstance(tags_raw, str):
            tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
        else:
            tags = tuple(str(t) for t in tags_raw)

        author = arguments.get("author") or "agent:unknown"
        mem_id = str(_uuid.uuid4())
        mem = Memory(
            id=mem_id, neuron_id=neuron_id, lobe=arguments.get("lobe"),
            type=mem_type, title=title, body=body, author=author,
            created_ts=int(_time.time()), tags=tags,
            decay_score=1.0, status="active",
        )
        embedding = embed_memory(title, body)
        conn = open_memories_db(cerebrofy_dir)
        write_memory(conn, mem, embedding)
        conn.commit()
        conn.close()

        result: dict[str, Any] = {
            "id": mem_id, "neuron_id": neuron_id, "created_ts": mem.created_ts,
        }
        if warning_msg:
            result["warning"] = warning_msg
        from mcp.types import TextContent
        return [TextContent(type="text", text=_json.dumps(result, indent=2))]
    except Exception as exc:
        return _make_error_content(f"cerebrofy_remember failed: {exc}")


def _handle_recall(arguments: dict[str, Any]) -> list[Any]:
    import json as _json
    from mcp.types import TextContent

    query = arguments.get("query", "").strip()
    if not query:
        return _make_error_content("cerebrofy_recall: 'query' is required")

    try:
        root = require_repo_root(Path.cwd())
    except Exception:
        return [TextContent(type="text", text=_json.dumps({"memories": [], "count": 0}))]

    cerebrofy_dir = root / ".cerebrofy"
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not memories_db.exists():
        return [TextContent(type="text", text=_json.dumps({"memories": [], "count": 0}))]

    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.search import recall_memories
        from cerebrofy.memory.store import open_memories_db

        conn = open_memories_db(cerebrofy_dir)
        embedding = embed_memory(query, "")
        limit, _limit_err = _parse_int_arg(arguments, "limit", 10, maximum=_MAX_LIMIT)
        if _limit_err is not None:
            return _make_error_content(_limit_err)
        results = recall_memories(
            conn, embedding,
            limit=limit,
            type_filter=arguments.get("type"),
            lobe_filter=arguments.get("lobe"),
            include_stale=bool(arguments.get("include_stale", False)),
        )
        conn.close()

        out = {
            "memories": [
                {
                    "id": m.id, "type": m.type, "title": m.title, "body": m.body,
                    "neuron": m.neuron_id, "lobe": m.lobe, "author": m.author,
                    "created_ts": m.created_ts, "tags": list(m.tags),
                    "decay_score": m.decay_score, "status": m.status,
                    "relevance_score": score,
                }
                for m, score in results
            ],
            "count": len(results),
        }
        return [TextContent(type="text", text=_json.dumps(out, indent=2))]
    except Exception as exc:
        return [TextContent(type="text", text=_json.dumps({"memories": [], "error": str(exc)}))]


def _handle_memories(arguments: dict[str, Any]) -> list[Any]:
    import json as _json
    from mcp.types import TextContent

    neuron = arguments.get("neuron")
    lobe = arguments.get("lobe")
    if not neuron and not lobe:
        return _make_error_content("cerebrofy_memories: provide 'neuron' or 'lobe'")

    try:
        root = require_repo_root(Path.cwd())
    except Exception:
        return [TextContent(type="text", text=_json.dumps({"memories": [], "count": 0}))]

    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return [TextContent(type="text", text=_json.dumps({"memories": [], "count": 0}))]

    try:
        from cerebrofy.memory.store import list_memories, open_memories_db

        conn = open_memories_db(cerebrofy_dir)
        neuron_id: str | None = None
        if neuron:
            db_path = cerebrofy_dir / "db" / "cerebrofy.db"
            from cerebrofy.db.connection import open_db
            idx = open_db(db_path)
            rows = idx.execute(
                "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                (neuron, f"%::{neuron}"),
            ).fetchall()
            idx.close()
            if rows:
                neuron_id = rows[0][0]

        memories = list_memories(
            conn, neuron_id=neuron_id, lobe=lobe,
            type_filter=arguments.get("type"),
            include_stale=bool(arguments.get("include_stale", False)),
        )
        conn.close()

        out = {
            "memories": [
                {
                    "id": m.id, "type": m.type, "title": m.title, "body": m.body,
                    "neuron": m.neuron_id, "lobe": m.lobe, "author": m.author,
                    "created_ts": m.created_ts, "tags": list(m.tags),
                    "decay_score": m.decay_score, "status": m.status,
                }
                for m in memories
            ],
            "count": len(memories),
        }
        return [TextContent(type="text", text=_json.dumps(out, indent=2))]
    except Exception as exc:
        return _make_error_content(f"cerebrofy_memories failed: {exc}")


def _handle_build(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent
    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")
    code, output = _run_cerebrofy(["build"], str(root))
    status = "success" if code == 0 else "error"
    return [TextContent(type="text", text=f"[{status}]\n{output}")]


def _handle_update(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent
    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")
    path: str | None = arguments.get("path")
    cmd = ["update", path] if path else ["update"]
    code, output = _run_cerebrofy(cmd, str(root))
    status = "success" if code == 0 else "error"
    return [TextContent(type="text", text=f"[{status}]\n{output}")]


def _handle_validate(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent
    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")
    code, output = _run_cerebrofy(["validate"], str(root))
    drift_label = {0: "clean", 1: "minor_drift", 2: "structural_drift"}.get(code, "error")
    return [TextContent(type="text", text=f"[{drift_label}]\n{output}")]


def _handle_impact(arguments: dict[str, Any]) -> list[Any]:
    """Pre-change impact prediction for a target neuron."""
    from mcp.types import TextContent

    target: str = arguments.get("target", "")
    if not target:
        return _make_error_content("[error] 'target' is required.")

    depth: int = int(arguments.get("depth", 2))
    show_tests: bool = bool(arguments.get("show_tests", True))

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    conn = _open_db_ro(root)
    try:
        from cerebrofy.analysis.impact import compute_impact, resolve_target
        from cerebrofy.analysis.sequence import build_sequence
        from cerebrofy.db.connection import check_schema_version

        try:
            check_schema_version(conn)
        except ValueError as exc:
            return _make_error_content(f"Schema version mismatch: {exc}. Run 'cerebrofy migrate'.")

        neuron = resolve_target(target, conn)
        if neuron is None:
            return _make_error_content(
                f"[NO_INDEX] Neuron '{target}' not found. Run 'cerebrofy build' to refresh the index."
            )

        result = compute_impact(neuron, conn, depth=depth, show_tests=show_tests,
                                cerebrofy_dir=root / ".cerebrofy")
        sequence = build_sequence(
            neuron,
            result.callers_by_depth,
            result.runtime_boundary_callers,
            conn,
        )
    finally:
        conn.close()

    import json as _json
    out: dict[str, Any] = {
        "target": {
            "id": result.target.id,
            "name": result.target.name,
            "file": result.target.file,
            "line_start": result.target.line_start,
            "lobe": result.target.lobe,
        },
        "callers_depth1": [
            {"name": n.name, "file": n.file, "line_start": n.line_start}
            for n in result.callers_by_depth.get(1, [])
        ],
        "callers_depth2": [
            {"name": n.name, "file": n.file, "line_start": n.line_start}
            for n in result.callers_by_depth.get(2, [])
        ],
        "lobe_spread": result.lobe_spread,
        "estimated_loc": result.estimated_loc,
        "complexity_rating": result.complexity_rating,
        "runtime_boundary_callers": result.runtime_boundary_callers,
        "covering_tests": [
            {"name": t.name, "file": t.file} for t in result.covering_tests
        ] if show_tests else [],
        "uncovered_callers": result.uncovered_callers if show_tests else [],
        "memory_warnings": result.memory_warnings,
        "refactoring_sequence": [
            {
                "step": s.step,
                "description": s.description,
                "neuron_ids": s.neuron_ids,
                "is_runtime_boundary": s.is_runtime_boundary,
            }
            for s in sequence
        ],
    }
    return [TextContent(type="text", text=_json.dumps(out, indent=2))]


def _handle_silo(arguments: dict[str, Any]) -> list[Any]:
    """Knowledge silo detector — git blame × call graph = bus factor risk per neuron."""
    from mcp.types import TextContent

    depth: int = int(arguments.get("depth", 2))
    min_callers: int = int(arguments.get("min_callers", 1))
    top, _top_err = _parse_int_arg(arguments, "top", 20, maximum=_MAX_RESULT_TOP)
    if _top_err is not None:
        return _make_error_content(_top_err)
    lobe_filter: str | None = arguments.get("lobe")
    author_filter: str | None = arguments.get("author")
    risk_filter: str | None = arguments.get("risk_level")
    write_memories: bool = bool(arguments.get("write_memories", False))

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    conn = _open_db_ro(root)
    try:
        from cerebrofy.db.connection import check_schema_version
        from cerebrofy.analysis.silo_detector import compute_silo_report

        try:
            check_schema_version(conn)
        except (ValueError, sqlite3.OperationalError) as exc:
            return _make_error_content(f"Schema version mismatch: {exc}. Run 'cerebrofy migrate'.")

        report = compute_silo_report(
            conn=conn,
            repo_root=root,
            depth=depth,
            min_callers=min_callers,
            top=top,
            lobe_filter=lobe_filter,
            author_filter=author_filter,
            risk_filter=risk_filter,
            write_memories=write_memories,
            cerebrofy_dir=root / ".cerebrofy" if write_memories else None,
        )
    finally:
        conn.close()

    import dataclasses
    import json as _json
    out: dict[str, Any] = {
        "as_of_commit": report.as_of_commit,
        "total_neurons_scanned": report.total_neurons_scanned,
        "silos_detected": report.silos_detected,
        "neurons": [dataclasses.asdict(n) for n in report.neurons],
    }
    return [TextContent(type="text", text=_json.dumps(out, indent=2))]


def _handle_coverage_gap(arguments: dict[str, Any]) -> list[Any]:
    """Test Coverage Gap Predictor — rank uncovered neurons by blast_radius × velocity."""
    from mcp.types import TextContent

    days: int = int(arguments.get("days", 30))
    depth: int = int(arguments.get("depth", 2))
    min_blast: float = float(arguments.get("min_blast", 0.0))
    top, _top_err = _parse_int_arg(arguments, "top", 20, maximum=_MAX_RESULT_TOP)
    if _top_err is not None:
        return _make_error_content(_top_err)
    lobe_filter: str | None = arguments.get("lobe")
    risk_filter: str | None = arguments.get("risk_level")
    write_memories: bool = bool(arguments.get("write_memories", False))

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    conn = _open_db_ro(root)
    try:
        from cerebrofy.db.connection import check_schema_version
        from cerebrofy.analysis.coverage_gap import compute_coverage_gap_report

        try:
            check_schema_version(conn)
        except (ValueError, sqlite3.OperationalError) as exc:
            return _make_error_content(f"Schema version mismatch: {exc}. Run 'cerebrofy migrate'.")

        report = compute_coverage_gap_report(
            conn=conn,
            repo_root=root,
            days=days,
            depth=depth,
            min_blast=min_blast,
            top=top,
            lobe_filter=lobe_filter,
            risk_filter=risk_filter,
            write_memories=write_memories,
            cerebrofy_dir=root / ".cerebrofy" if write_memories else None,
        )
    finally:
        conn.close()

    import dataclasses
    import json as _json
    out: dict[str, Any] = {
        "as_of_commit": report.as_of_commit,
        "total_neurons_scanned": report.total_neurons_scanned,
        "uncovered_count": report.uncovered_count,
        "coverage_source": report.coverage_source,
        "velocity_days": report.velocity_days,
        "neurons": [dataclasses.asdict(n) for n in report.neurons],
    }
    return [TextContent(type="text", text=_json.dumps(out, indent=2))]


def _handle_vuln(arguments: dict[str, Any]) -> list[Any]:
    """Vulnerability blast radius — find which functions call a vulnerable package."""
    from mcp.types import TextContent

    package: str = arguments.get("package", "")
    if not package:
        return _make_error_content("[error] 'package' is required.")

    function_pattern: str | None = arguments.get("function_pattern")
    depth: int = int(arguments.get("depth", 2))
    write_memories: bool = bool(arguments.get("write_memories", False))

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    conn = _open_db_ro(root)
    try:
        from cerebrofy.db.connection import check_schema_version
        from cerebrofy.security.vuln_scanner import compute_vuln_blast_radius

        try:
            check_schema_version(conn)
        except (ValueError, sqlite3.OperationalError) as exc:
            return _make_error_content(f"Schema version mismatch: {exc}. Run 'cerebrofy migrate'.")

        result = compute_vuln_blast_radius(
            package=package,
            function_pattern=function_pattern,
            conn=conn,
            depth=depth,
            cerebrofy_dir=root / ".cerebrofy" if write_memories else None,
            write_memories=write_memories,
            root=root,
        )
    finally:
        conn.close()

    if not result.direct_callers:
        return _make_error_content(
            f"[PACKAGE_NOT_USED] Package '{package}' not found in the call graph. "
            "Not imported, or index needs rebuild."
        )

    import json as _json
    out: dict[str, Any] = {
        "package": result.package,
        "function_pattern": result.function_pattern,
        "pinned_version": result.pinned_version,
        "direct_callers": [
            {
                "name": c.name,
                "file": c.file,
                "line_start": c.line_start,
                "call_target": c.call_target,
                "is_trust_boundary": c.is_trust_boundary,
                "is_test": c.is_test,
            }
            for c in result.direct_callers
        ],
        "upstream_count": result.upstream_count,
        "critical_exposure": [
            {
                "entry_point": f"{p.entry_point_file}::{p.entry_point_name}",
                "call_chain": p.call_chain,
                "exposure_score": p.exposure_score,
            }
            for p in result.critical_exposure
        ],
        "low_exposure": [
            {"name": c.name, "file": c.file, "is_test": c.is_test}
            for c in result.low_exposure
        ],
        "remediation_sequence": result.remediation_sequence,
        "memories_written": result.memories_written,
    }
    return [TextContent(type="text", text=_json.dumps(out, indent=2))]


def _handle_arch_check(arguments: dict[str, Any]) -> list[Any]:
    """Run .cerebrofy/arch-rules.yaml checks over the live call graph."""
    from mcp.types import TextContent

    rule_name = str(arguments.get("rule", "all") or "all")
    fmt = str(arguments.get("format", "markdown") or "markdown").lower()
    since_ref = arguments.get("since")

    try:
        root = require_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    from cerebrofy.arch.rules import RulesError
    from cerebrofy.config.loader import load_arch_rules

    try:
        rules = load_arch_rules(root)
    except RulesError as exc:
        return _make_error_content(f"[RULES_ERROR] {exc}")
    if rules is None:
        return _make_error_content(
            "[NO_RULES_FILE] .cerebrofy/arch-rules.yaml not found. "
            "Run 'cerebrofy arch init' to create one."
        )
    if rule_name != "all" and rule_name not in rules.rule_names:
        return _make_error_content(
            f"[RULE_NOT_FOUND] Rule '{rule_name}' does not exist. "
            f"Available: {', '.join(rules.rule_names) or '(none)'}"
        )

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _make_error_content(
            "[NO_INDEX] Index not found. Run 'cerebrofy build' first."
        )

    changed_files: frozenset[str] | None = None
    if since_ref:
        from cerebrofy.arch.checker import changed_files_since

        try:
            changed_files = frozenset(changed_files_since(root, str(since_ref)))
        except ValueError as exc:
            return _make_error_content(f"[error] {exc}")

    try:
        from cerebrofy.arch.checker import run_arch_check
        from cerebrofy.arch.reporter import render_annotations, render_json, render_markdown
        from cerebrofy.config.loader import load_config
        from cerebrofy.db.connection import open_db_readonly
        from cerebrofy.intent.loader import sprint_priority_lobes

        config = load_config(root / ".cerebrofy" / "config.yaml")
        conn = open_db_readonly(db_path)
        try:
            result = run_arch_check(
                rules,
                conn,
                config.lobes,
                repo_root=root,
                rule_name=None if rule_name == "all" else rule_name,
                changed_files=changed_files,
                # Idea #23: escalate warning rules on sprint-priority lobes.
                # Epistemic confidence (Idea #22) is injected by _with_epistemic
                # at dispatch time, so it is not recomputed here.
                priority_lobes=sprint_priority_lobes(root / ".cerebrofy"),
            )
        finally:
            conn.close()

        if fmt == "json":
            text = render_json(result)
        elif fmt == "github-annotations":
            text = render_annotations(result)
        else:
            text = render_markdown(result)
        return [TextContent(type="text", text=text or "(no violations)")]
    except FileNotFoundError as exc:
        return _make_error_content(f"[NO_INDEX] {exc}")
    except RulesError as exc:
        return _make_error_content(f"[RULES_ERROR] {exc}")


# ---------------------------------------------------------------------------
# Declarative tool dispatch (replaces the per-tool ``_dispatch_tool`` elif chain)
# ---------------------------------------------------------------------------
# ``TOOL_SPECS``/``SPEC_BY_NAME`` (from :mod:`cerebrofy.mcp.tool_specs`) are the
# single source of truth for the catalog: names, order, descriptions, schemas,
# and which tools receive epistemic/intent injection. ``_HANDLERS`` binds each
# spec's ``handler_name`` to the module-level ``_handle_*`` implementation defined
# above. Wiring is checked at import time: a renamed or deleted handler fails
# loudly (ImportError) instead of producing a silent "Unknown tool" error at
# call time, and the explicit mapping lets static analysis see every handler as
# used (ruff F401).
_HANDLERS: dict[str, Callable[[dict[str, Any]], list[Any]]] = {
    "_handle_search_code": _handle_search_code,
    "_handle_get_neuron": _handle_get_neuron,
    "_handle_list_lobes": _handle_list_lobes,
    "_handle_list_resources": _handle_list_resources,
    "_handle_context": _handle_context,
    "_handle_blast_radius": _handle_blast_radius,
    "_handle_epistemic": _handle_epistemic,
    "_handle_health": _handle_health,
    "_handle_intent": _handle_intent,
    "_handle_build": _handle_build,
    "_handle_update": _handle_update,
    "_handle_validate": _handle_validate,
    "_handle_remember": _handle_remember,
    "_handle_recall": _handle_recall,
    "_handle_memories": _handle_memories,
    "_handle_link_memories": _handle_link_memories,
    "_handle_trace_history": _handle_trace_history,
    "_handle_onboard": _handle_onboard,
    "_handle_impact": _handle_impact,
    "_handle_silo": _handle_silo,
    "_handle_coverage_gap": _handle_coverage_gap,
    "_handle_vuln": _handle_vuln,
    "_handle_upgrade": _handle_upgrade,
    "_handle_arch_check": _handle_arch_check,
    "_handle_session_start": _handle_session_start,
    "_handle_session_end": _handle_session_end,
    "_handle_session_show": _handle_session_show,
    "_handle_plan": _handle_plan,
    "_handle_changelog": _handle_changelog,
    "_handle_governance": _handle_governance,
    "_handle_review": _handle_review,
}
_unwired = [s.name for s in TOOL_SPECS if s.handler_name not in _HANDLERS]
if _unwired:
    raise ImportError(
        "TOOL_SPECS references handler(s) not wired in _HANDLERS: " + ", ".join(_unwired)
    )
del _unwired


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Dispatch *name* to its handler with the original error-mapping semantics.

    Replaces the previous 28-branch ``_dispatch_tool`` elif chain with a
    declarative lookup against :data:`TOOL_SPECS` (order/descriptions/schemas),
    :data:`SPEC_BY_NAME` (routing), and :data:`_HANDLERS` (implementation).

    Behaviour preserved verbatim:

    * unknown tool -> ``Unknown tool: {name}``;
    * data-reading tools (``spec.inject``) receive ``_with_epistemic`` then
      ``_with_intent`` enrichment, quietly skipped if the repository root
      cannot be resolved;
    * the exact outer exception mapping:
      ``FileNotFoundError`` -> init hint, ``ValueError`` (schema/embed branches),
      ``subprocess.TimeoutExpired`` -> timeout message, generic ``Exception``
      -> stderr print + ``[error]`` payload.
    """
    args = arguments or {}
    spec = SPEC_BY_NAME.get(name)
    if spec is None:
        return _make_error_content(f"Unknown tool: {name}")

    try:
        result = _HANDLERS[spec.handler_name](args)
        if not spec.inject:
            return result

        # Cross-cutting enrichment for all data-reading tools
        try:
            root = require_repo_root(Path.cwd())
            result = _with_epistemic(result, root)
            result = _with_intent(result, root)
            return result
        except Exception:
            return result

    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}\nRun 'cerebrofy init' first.")
    except ValueError as exc:
        msg = str(exc)
        if "schema" in msg.lower():
            return _make_error_content("Schema version mismatch. Run 'cerebrofy migrate'.")
        if "embed" in msg.lower():
            return _make_error_content("Embedding model mismatch. Run 'cerebrofy build'.")
        return _make_error_content(f"[error] {msg}")
    except subprocess.TimeoutExpired:
        return _make_error_content(
            f"[error] Command timed out after {DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS} seconds."
        )
    except Exception as exc:
        print(f"cerebrofy mcp: unexpected error: {exc}", file=sys.stderr)
        return _make_error_content(f"[error] {exc}")


# ---------------------------------------------------------------------------
# Server entrypoint
# ---------------------------------------------------------------------------

# Bootstrapped once at start-up so every handler operates on the same project
# regardless of later CWD changes. Honors (in order): an explicit ``root``
# argument, the ``CEREBROFY_ROOT`` env var, then a CWD walk-up.
# ``set_bound_root`` is imported from ``cerebrofy.utils.paths`` and read by the
# shared ``find_repo_root``/``require_repo_root`` used by handlers.

_BOOTSTRAP_NOTE = (
    "Run 'cerebrofy init' first, or set CEREBROFY_ROOT / pass --root "
    "pointing at a valid Cerebrofy project."
)


def _bootstrap_root(root: Path | str | None) -> Path | None:
    """Resolve an explicit repo root for the lifetime of the server.

    An explicit *root* (``--root``) or a ``CEREBROFY_ROOT`` env var pins the
    project for the whole process. Without either, ``None`` is returned and the
    server keeps the documented per-call CWD routing (one MCP entry serving
    multiple repos). An invalid explicit binding raises
    :class:`InvalidRepoRootError` so the server refuses to start rather than
    silently scanning the wrong project.
    """
    if root is not None:
        resolved = Path(root).resolve()
        if not (resolved / ".cerebrofy" / "config.yaml").is_file():
            raise InvalidRepoRootError(
                f"--root {root!r} does not contain .cerebrofy/config.yaml. "
                + _BOOTSTRAP_NOTE
            )
        return resolved
    if not os.environ.get("CEREBROFY_ROOT"):
        return None
    # Env var is set: resolve it once and fail closed if it is invalid.
    found = find_repo_root(Path.cwd())
    if found is None:
        raise FileNotFoundError(
            "CEREBROFY_ROOT did not resolve to a Cerebrofy project. "
            + _BOOTSTRAP_NOTE
        )
    return found


def _bind_launch_boundary(start: Path | None = None) -> Path | None:
    """Set the process-wide launch boundary for an unbound server (C1/S1).

    Called at start-up when no explicit ``--root`` / ``CEREBROFY_ROOT`` pin is
    given. Per-call CWD routing is preserved, but the walk-up can never leave
    the launch directory: launched inside a project the boundary is that
    project root (sibling projects stay unreachable); launched at a non-project
    directory (e.g. a workspace root) the boundary is the launch CWD itself, so
    the repos *beneath* it remain routable while siblings and parents do not.

    Returns the launch project root when the launch CWD was inside one, else
    ``None`` (workspace-root mode).
    """
    cwd = (start if start is not None else Path.cwd()).resolve()
    launch_root = find_repo_root(cwd)
    set_root_boundary(launch_root if launch_root is not None else cwd)
    return launch_root


async def run_mcp_server(root: Path | str | None = None) -> None:
    """Start the cerebrofy MCP stdio server.

    *root* (or the ``CEREBROFY_ROOT`` env var) pins the project the server
    operates on. Pinning happens **once** here: every handler then resolves the
    root from this binding instead of re-walking from CWD, so a manipulated
    working directory cannot redirect the server at another project's
    ``cerebrofy.db`` / ``sessions.db`` / ``memories.db``.

    When neither is supplied the server keeps the documented per-call CWD
    routing, so one MCP entry can serve multiple repos.
    """
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool

    bound = _bootstrap_root(root)
    if bound is not None:
        set_bound_root(bound)
        source = "explicit --root" if root is not None else "CEREBROFY_ROOT"
        print(
            f"cerebrofy mcp: bound to project root {bound} ({source})",
            file=sys.stderr,
        )
    else:
        launch_root = _bind_launch_boundary()
        if launch_root is not None:
            print(
                "cerebrofy mcp: CWD routing enabled within launch boundary "
                f"{launch_root} (project root); sibling projects are blocked. "
                "Set CEREBROFY_ROOT or pass --root to pin the project",
                file=sys.stderr,
            )
        else:
            print(
                "cerebrofy mcp: CWD routing enabled within launch boundary "
                f"{Path.cwd().resolve()} (workspace root); repos beneath it are "
                "served, siblings are blocked. Set CEREBROFY_ROOT or pass "
                "--root to pin the project",
                file=sys.stderr,
            )

    app = CerebrofyMCPServer("cerebrofy")

    @app.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=s.name, description=s.description, inputSchema=s.input_schema)
            for s in TOOL_SPECS
        ]

    @app.call_tool()  # type: ignore[no-untyped-call,untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        """Dispatch the tool call, then offer it to the session recorder (#11)."""
        result = await dispatch_tool(name, arguments)
        _record_session_event(name, arguments or {}, result)
        return result

    # ── MCP Resources ────────────────────────────────────────────────────────
    # Expose codebase graph data as URI-addressable ambient context so AI
    # clients can subscribe without an explicit tool call.

    _watcher_state: dict[str, Any] = {"started": False, "task": None}
    _subscriptions: set[str] = set()

    def _capture_session() -> None:
        """Remember the active client session and start the index watcher (once)."""
        _start_index_watcher(app, _subscriptions, _watcher_state)

    @app.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_resources() -> list[Any]:
        from mcp.types import Resource
        from cerebrofy.mcp.resources import list_resource_entries

        _capture_session()

        try:
            root = require_repo_root(Path.cwd())
        except FileNotFoundError:
            return []

        return [
            Resource(
                uri=e["uri"],
                name=e["name"],
                description=e["description"],
                mimeType=e["mime_type"],
            )
            for e in list_resource_entries(root)
            if not e["template"]
        ]

    @app.list_resource_templates()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_resource_templates() -> list[Any]:
        from mcp.types import ResourceTemplate
        from cerebrofy.mcp.resources import list_resource_entries

        try:
            root = require_repo_root(Path.cwd())
        except FileNotFoundError:
            root = Path.cwd()  # templates are index-independent; lobes will be empty

        return [
            ResourceTemplate(
                uriTemplate=e["uri"],
                name=e["name"],
                description=e["description"],
                mimeType=e["mime_type"],
            )
            for e in list_resource_entries(root)
            if e["template"]
        ]

    @app.subscribe_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def subscribe_resource(uri: Any) -> None:
        _subscriptions.add(str(uri))
        _capture_session()

    @app.unsubscribe_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def unsubscribe_resource(uri: Any) -> None:
        _subscriptions.discard(str(uri))

    @app.read_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def read_resource(uri: Any) -> list[Any]:
        from urllib.parse import parse_qs, unquote, urlsplit

        from mcp.server.lowlevel.helper_types import ReadResourceContents
        from cerebrofy.mcp.resources import (
            blast_radius_summary, current_health, entry_points, file_neurons,
            get_neuron, memories_for_neuron, neuron_callers, neuron_source,
            read_lobe, read_map, search_resource_results,
        )

        _capture_session()

        uri_str = str(uri)

        try:
            root = require_repo_root(Path.cwd())
        except FileNotFoundError as exc:
            raise ValueError(f"No Cerebrofy index found: {exc}") from exc

        # ── cerebrofy://graph/map ────────────────────────────────────────────
        if uri_str == "cerebrofy://graph/map":
            return [ReadResourceContents(content=read_map(root), mime_type="text/markdown")]

        # ── cerebrofy://graph/entry-points ──────────────────────────────────
        if uri_str == "cerebrofy://graph/entry-points":
            conn = _open_db_ro(root)
            try:
                data = entry_points(conn)
            finally:
                conn.close()
            return [ReadResourceContents(
                content=json.dumps(data, indent=2), mime_type="application/json"
            )]

        # ── cerebrofy://health/current ───────────────────────────────────────
        if uri_str == "cerebrofy://health/current":
            conn = _open_db_ro(root)
            try:
                snapshot = current_health(conn)
            finally:
                conn.close()
            return [ReadResourceContents(
                content=json.dumps(snapshot or {}, indent=2),
                mime_type="application/json",
            )]

        # ── cerebrofy://lobes/{name} ─────────────────────────────────────────
        if uri_str.startswith("cerebrofy://lobes/"):
            name = unquote(uri_str[len("cerebrofy://lobes/"):])
            if not name:
                raise ValueError("Lobe name is required: cerebrofy://lobes/{name}")
            return [ReadResourceContents(content=read_lobe(name, root), mime_type="text/markdown")]

        # ── cerebrofy://neurons/search?q={query} ─────────────────────────────
        # Must be matched before the generic cerebrofy://neurons/{id} branch.
        if uri_str == "cerebrofy://neurons/search" or uri_str.startswith("cerebrofy://neurons/search?"):
            query = (parse_qs(urlsplit(uri_str).query).get("q") or [""])[0].strip()
            if not query:
                raise ValueError(
                    "Query parameter 'q' is required: cerebrofy://neurons/search?q={query}"
                )
            try:
                results = search_resource_results(query, root)
            except ValueError as exc:
                raise ValueError(f"Search unavailable: {exc}") from exc
            return [ReadResourceContents(
                content=json.dumps(
                    {"query": query, "results": results, "count": len(results)}, indent=2
                ),
                mime_type="application/json",
            )]

        # ── cerebrofy://neurons/file/{file_path} ─────────────────────────────
        # Must be matched before the generic cerebrofy://neurons/{id} branch.
        if uri_str.startswith("cerebrofy://neurons/file/"):
            file_path = unquote(uri_str[len("cerebrofy://neurons/file/"):])
            if not file_path:
                raise ValueError("File path is required: cerebrofy://neurons/file/{file_path}")
            conn = _open_db_ro(root)
            try:
                neurons = file_neurons(file_path, conn)
            finally:
                conn.close()
            return [ReadResourceContents(
                content=json.dumps(neurons, indent=2), mime_type="application/json"
            )]

        # ── cerebrofy://neurons/{neuron_id} ──────────────────────────────────
        if uri_str.startswith("cerebrofy://neurons/"):
            neuron_id = unquote(uri_str[len("cerebrofy://neurons/"):])
            if not neuron_id:
                raise ValueError("Neuron ID is required: cerebrofy://neurons/{neuron_id}")
            conn = _open_db_ro(root)
            try:
                neuron = get_neuron(neuron_id, conn)
                callers = neuron_callers(neuron_id, conn) if neuron else []
            finally:
                conn.close()
            if neuron is None:
                raise ValueError(f"Neuron '{neuron_id}' not found in index.")
            neuron["callers"] = callers
            neuron["source"] = neuron_source(neuron, root)
            return [ReadResourceContents(
                content=json.dumps(neuron, indent=2), mime_type="application/json"
            )]

        # ── cerebrofy://memories/{neuron_id} ─────────────────────────────────
        if uri_str.startswith("cerebrofy://memories/"):
            neuron_id = unquote(uri_str[len("cerebrofy://memories/"):])
            if not neuron_id:
                raise ValueError("Neuron ID is required: cerebrofy://memories/{neuron_id}")
            mems = memories_for_neuron(neuron_id, root)
            return [ReadResourceContents(
                content=json.dumps(mems, indent=2), mime_type="application/json"
            )]

        # ── cerebrofy://blast-radius/{neuron_id} ─────────────────────────────
        if uri_str.startswith("cerebrofy://blast-radius/"):
            target = unquote(uri_str[len("cerebrofy://blast-radius/"):])
            if not target:
                raise ValueError("Neuron ID is required: cerebrofy://blast-radius/{neuron_id}")
            conn = _open_db_ro(root)
            try:
                payload = blast_radius_summary(target, conn)
            finally:
                conn.close()
            if payload is None:
                raise ValueError(f"Neuron '{target}' not found in index.")
            return [ReadResourceContents(
                content=json.dumps(payload, indent=2), mime_type="application/json"
            )]

        raise ValueError(f"Unknown resource URI: {uri_str}")

    async with stdio_server() as (read_stream, write_stream):
        # TODO(integration-20): add an SSE transport option here (cloud sessions,
        # opt-in sync); recording itself stays local-only until then.
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(NotificationOptions(resources_changed=True)),
        )
