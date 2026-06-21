"""MCP stdio server for cerebrofy.

Exposes six tools:
  search_code         — hybrid KNN + BFS semantic search (primary navigation)
  get_neuron          — fetch a single Neuron by name or file:line
  list_lobes          — return available lobes with summary file paths
  cerebrofy_build     — full atomic re-index
  cerebrofy_update    — incremental re-index of changed files
  cerebrofy_validate  — drift check (zero writes)
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_repo_root(start: Path) -> Path:
    """Walk up from *start* searching for .cerebrofy/config.yaml."""
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    raise FileNotFoundError(
        "No Cerebrofy config found in current directory or any parent. "
        "Run 'cerebrofy init' first."
    )


def _run_cerebrofy(args: list[str], cwd: str, timeout: int = 300) -> tuple[int, str]:
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
    from mcp.types import TextContent
    return [TextContent(type="text", text=message)]


def _open_db_ro(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        raise FileNotFoundError(
            f"Index not found at {db_path}. Run 'cerebrofy build' first."
        )
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _handle_search_code(arguments: dict[str, Any]) -> list[Any]:
    """Hybrid semantic + keyword search — primary navigation tool."""
    from mcp.types import TextContent

    query: str = arguments.get("query", "")
    top_k: int = int(arguments.get("top_k", 10))
    lobe_filter: str | None = arguments.get("lobe")

    if not query:
        return _make_error_content("[error] 'query' is required.")

    root = _find_repo_root(Path.cwd())
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

    root = _find_repo_root(Path.cwd())
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
    return [TextContent(type="text", text=json.dumps({"neurons": neurons}, indent=2))]


def _handle_list_lobes(arguments: dict[str, Any]) -> list[Any]:
    """Return available lobes by scanning the lobes markdown directory."""
    from mcp.types import TextContent

    root = _find_repo_root(Path.cwd())
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
        root = _find_repo_root(Path.cwd())
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
        root = _find_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")

    conn = _open_db_ro(root)
    try:
        from cerebrofy.analysis.blast_radius import (
            compute_blast_radius_report,
            format_pr_comment,
            neuron_for_target,
        )
        from cerebrofy.db.connection import check_schema_version

        try:
            check_schema_version(conn)
        except ValueError as exc:
            return _make_error_content(f"Schema version mismatch: {exc}. Run 'cerebrofy migrate'.")

        neuron = neuron_for_target(target, conn)
        if neuron is None:
            return _make_error_content(
                f"[NEURON_NOT_FOUND] Neuron '{target}' not found. Run 'cerebrofy build' first."
            )

        report = compute_blast_radius_report([neuron], conn, depth=depth)
    finally:
        conn.close()

    if fmt == "markdown":
        return [TextContent(type="text", text=format_pr_comment(report))]

    import json as _json
    nbr = report.changed_neurons[0]
    out: dict[str, Any] = {
        "target_neuron": {"name": nbr.neuron.name, "file": nbr.neuron.file, "line": nbr.neuron.line_start},
        "callers": [
            {"name": n.name, "file": n.file, "line": n.line_start, "depth": 1}
            for n in nbr.callers_depth1
        ] + [
            {"name": n.name, "file": n.file, "line": n.line_start, "depth": 2}
            for n in nbr.callers_depth2
        ],
        "uncovered_callers": nbr.uncovered_callers,
        "risk_score": round(nbr.risk_score, 3),
        "risk_label": nbr.risk_label,
        "lobe_spread": nbr.lobe_spread,
        "runtime_boundary_callers": nbr.runtime_boundary_callers,
        "summary": format_pr_comment(report),
    }
    return [TextContent(type="text", text=_json.dumps(out, indent=2))]


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
        root = _find_repo_root(Path.cwd())
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


def _handle_health(arguments: dict[str, Any]) -> list[Any]:
    """Return current health snapshot with delta from previous build."""
    from mcp.types import TextContent

    since_build: int = int(arguments.get("since_build", 1))
    metric: str = arguments.get("metric", "all")
    fmt: str = arguments.get("format", "markdown")

    try:
        root = _find_repo_root(Path.cwd())
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

        if fmt == "json":
            text = to_export_json(metrics, prev, ts, commit)
        else:
            text = format_health_snapshot(metrics, prev, ts, commit)

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
        root = _find_repo_root(Path.cwd())
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


def _handle_build(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent
    try:
        root = _find_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")
    code, output = _run_cerebrofy(["build"], str(root))
    status = "success" if code == 0 else "error"
    return [TextContent(type="text", text=f"[{status}]\n{output}")]


def _handle_update(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent
    try:
        root = _find_repo_root(Path.cwd())
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
        root = _find_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}")
    code, output = _run_cerebrofy(["validate"], str(root))
    drift_label = {0: "clean", 1: "minor_drift", 2: "structural_drift"}.get(code, "error")
    return [TextContent(type="text", text=f"[{drift_label}]\n{output}")]


# ---------------------------------------------------------------------------
# Server entrypoint
# ---------------------------------------------------------------------------

async def run_mcp_server() -> None:
    """Start the cerebrofy MCP stdio server."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool

    app = Server("cerebrofy")

    _EMPTY: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    _SEARCH_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query"},
            "top_k": {"type": "integer", "description": "Max results (default: 10)", "default": 10, "minimum": 1, "maximum": 50},
            "lobe": {"type": "string", "description": "Filter to a specific lobe/module (optional)"},
        },
        "required": ["query"],
    }

    _NEURON_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact function/class name"},
            "file": {"type": "string", "description": "Source file path (partial match)"},
            "line": {"type": "integer", "description": "Line number within the file (requires 'file')"},
        },
    }

    _UPDATE_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Specific file to re-index (omit for auto-detect)"},
        },
    }

    @app.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[Tool]:
        return [
            Tool(name="search_code", description=(
                "Hybrid semantic + keyword search over the Cerebrofy index. "
                "ALWAYS call this first when asked about code structure or behaviour. "
                "Returns ranked Neurons with file path and line number. "
                "Never glob-read source files — use this instead."
            ), inputSchema=_SEARCH_SCHEMA),
            Tool(name="get_neuron", description=(
                "Fetch details for a specific Neuron by name or file path. "
                "Use after search_code to get the full signature, docstring, and location."
            ), inputSchema=_NEURON_SCHEMA),
            Tool(name="list_lobes", description=(
                "List all indexed lobes (modules/packages) with summary file paths. "
                "Use for high-level orientation before searching."
            ), inputSchema=_EMPTY),
            Tool(name="cerebrofy_context", description=(
                "Build the optimal context window for a coding task within a token budget. "
                "Embeds the task, runs KNN + BFS, scores candidates by relevance, and "
                "greedy-packs neurons with tier degradation (full_source → signature → lobe_summary → name_only). "
                "Call this before starting any non-trivial coding task."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Natural language coding task description."},
                    "budget": {"type": "integer", "default": 8000, "description": "Token budget."},
                    "model": {"type": "string", "default": "auto", "description": "Model for token counting."},
                    "format": {"type": "string", "default": "json", "enum": ["json", "markdown", "claude-xml"]},
                },
                "required": ["task"],
            }),
            Tool(name="cerebrofy_blast_radius", description=(
                "Compute the blast radius of a changed neuron — every caller at depth 1 and 2, "
                "test coverage, lobe spread, and a risk score. "
                "Use after a PR diff to understand what a change affects before merging."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "Neuron to analyse. Accepts: "
                            "'file::name', 'file:line', or plain name."
                        ),
                    },
                    "depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
                    "format": {"type": "string", "default": "json", "enum": ["json", "markdown"]},
                },
                "required": ["target"],
            }),
            Tool(name="cerebrofy_epistemic", description=(
                "Return the epistemic confidence score for the current index — "
                "graph age, neurons changed since last build, unindexed languages, "
                "dynamic dispatch count, and a composite confidence score (0.5–1.0). "
                "Call this before any architectural decision to understand how much to "
                "trust the index. All other Cerebrofy tool responses include an "
                "'epistemic' field automatically."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "format": {"type": "string", "default": "json", "enum": ["json", "human"]},
                },
            }),
            Tool(name="cerebrofy_health", description=(
                "Return longitudinal codebase health metrics derived from the call graph. "
                "Includes coupling, blast radius trend, dead code %, lobe cohesion, "
                "test surface coverage, drift velocity, and hub concentration. "
                "Use to understand whether the codebase is improving or degrading over time."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "since_build": {"type": "integer", "default": 1, "description": "Compare against N builds ago."},
                    "metric": {"type": "string", "default": "all", "description": "Specific metric name or 'all'."},
                    "format": {"type": "string", "default": "markdown", "enum": ["markdown", "json"]},
                },
            }),
            Tool(name="cerebrofy_intent", description=(
                "Return the current product intent — sprint goals, active incidents, "
                "architectural direction, and team context. Pass 'lobe' or 'neuron' to "
                "get relevance scoring for a specific part of the codebase. "
                "Call this at the start of any task to understand team priorities and known risks."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "lobe": {"type": "string", "description": "Get intent relevance for a specific lobe (optional)"},
                    "neuron": {"type": "string", "description": "Get intent relevance for a specific neuron path (optional)"},
                    "format": {"type": "string", "default": "json", "enum": ["json", "human"]},
                },
            }),
            Tool(name="cerebrofy_build", description=(
                "Full atomic re-index of the entire repository. "
                "Use when the index is missing or a full rebuild is needed."
            ), inputSchema=_EMPTY),
            Tool(name="cerebrofy_update", description=(
                "Incremental re-index of changed files (auto-detected via git diff). "
                "Pass 'path' to limit to a specific file."
            ), inputSchema=_UPDATE_SCHEMA),
            Tool(name="cerebrofy_validate", description=(
                "Check for drift between source code and the index. "
                "Returns 'clean', 'minor_drift', or 'structural_drift'. Zero writes."
            ), inputSchema=_EMPTY),
        ]

    @app.call_tool()  # type: ignore[no-untyped-call,untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        args = arguments or {}
        # Subprocess tools don't benefit from epistemic injection
        _subprocess_tools = {"cerebrofy_build", "cerebrofy_update", "cerebrofy_validate"}

        try:
            if name == "cerebrofy_epistemic":
                # Returns its own full epistemic payload — no further injection needed
                return _handle_epistemic(args)
            elif name == "cerebrofy_intent":
                # Returns its own full intent payload — no further cross-cutting injection needed
                return _handle_intent(args)
            elif name == "cerebrofy_health":
                result = _handle_health(args)
            elif name == "cerebrofy_context":
                result = _handle_context(args)
            elif name == "cerebrofy_blast_radius":
                result = _handle_blast_radius(args)
            elif name == "search_code":
                result = _handle_search_code(args)
            elif name == "get_neuron":
                result = _handle_get_neuron(args)
            elif name == "list_lobes":
                result = _handle_list_lobes(args)
            elif name == "cerebrofy_build":
                return _handle_build(args)
            elif name == "cerebrofy_update":
                return _handle_update(args)
            elif name == "cerebrofy_validate":
                return _handle_validate(args)
            else:
                return _make_error_content(f"Unknown tool: {name}")

            # Cross-cutting enrichment for all data-reading tools
            try:
                root = _find_repo_root(Path.cwd())
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
            return _make_error_content("[error] Command timed out after 300 seconds.")
        except Exception as exc:
            print(f"cerebrofy mcp: unexpected error: {exc}", file=sys.stderr)
            return _make_error_content(f"[error] {exc}")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
