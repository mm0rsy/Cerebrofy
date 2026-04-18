"""MCP stdio server for cerebrofy.

Exposes eight tools:
  search_code         — hybrid semantic + keyword search (primary navigation)
  get_neuron          — fetch a single Neuron by name or file:line
  list_lobes          — return available lobes with summary file paths
  plan                — blast-radius analysis for a feature description
  tasks               — structured task list for a feature description
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
    from cerebrofy.search.hybrid import _embed_query, hybrid_search

    config = load_config(root / ".cerebrofy" / "config.yaml")
    embedding = _embed_query(query, config)
    lobe_dir = str(root / ".cerebrofy" / "lobes")

    result = hybrid_search(
        query=query,
        db_path=str(db_path),
        embedding=embedding,
        top_k=top_k,
        config_embed_model=config.embedding_model,
        lobe_dir=lobe_dir,
    )

    neurons = result.matched_neurons
    if lobe_filter:
        neurons = [n for n in neurons if lobe_filter.lower() in (n.lobe or "").lower()]

    if not neurons:
        return [TextContent(type="text", text=json.dumps({"results": [], "count": 0}))]

    hits = [
        {
            "name": n.name,
            "type": n.node_type,
            "file": n.file,
            "line": n.start_line,
            "lobe": n.lobe,
            "similarity": round(n.similarity, 3),
            "summary": (n.docstring or "")[:200],
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
                "SELECT id, name, node_type, file, start_line, end_line, lobe, docstring "
                "FROM neurons WHERE name = ? LIMIT 5",
                (name,),
            ).fetchall()
        else:
            q = (
                "SELECT id, name, node_type, file, start_line, end_line, lobe, docstring "
                "FROM neurons WHERE file LIKE ?"
            )
            params: list[Any] = [f"%{file}%"]
            if line is not None:
                q += " AND start_line <= ? AND end_line >= ?"
                params += [line, line]
            rows = conn.execute(q, params).fetchmany(5)
    finally:
        conn.close()

    if not rows:
        return [TextContent(type="text", text=json.dumps({"neurons": [], "message": "Not found."}))]

    cols = ("id", "name", "node_type", "file", "start_line", "end_line", "lobe", "docstring")
    neurons = [dict(zip(cols, row)) for row in rows]
    return [TextContent(type="text", text=json.dumps({"neurons": neurons}, indent=2))]


def _handle_list_lobes(arguments: dict[str, Any]) -> list[Any]:
    """Return available lobes with neuron counts and summary file paths."""
    from mcp.types import TextContent

    root = _find_repo_root(Path.cwd())
    conn = _open_db_ro(root)
    try:
        rows = conn.execute(
            "SELECT lobe, COUNT(*) as count FROM neurons "
            "WHERE lobe IS NOT NULL GROUP BY lobe ORDER BY count DESC"
        ).fetchall()
    finally:
        conn.close()

    lobes_dir = root / ".cerebrofy" / "lobes"
    lobes = []
    for lobe_name, count in rows:
        summary_file = lobes_dir / f"{lobe_name}_lobe.md"
        lobes.append({
            "name": lobe_name,
            "neuron_count": count,
            "summary_file": str(summary_file.relative_to(root)) if summary_file.exists() else None,
        })

    map_file = root / ".cerebrofy" / "cerebrofy_map.md"
    return [TextContent(type="text", text=json.dumps({
        "lobes": lobes,
        "full_map": str(map_file.relative_to(root)) if map_file.exists() else None,
    }, indent=2))]


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


def _handle_plan(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent

    description: str = arguments.get("description", "")
    top_k: int = int(arguments.get("top_k", 10))

    root = _find_repo_root(Path.cwd())
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _make_error_content("Index not found. Run 'cerebrofy build' first.")

    from cerebrofy.config.loader import load_config
    from cerebrofy.search.hybrid import _embed_query, hybrid_search
    from cerebrofy.commands.plan import _format_plan_json

    config = load_config(root / ".cerebrofy" / "config.yaml")
    embedding = _embed_query(description, config)
    lobe_dir = str(root / ".cerebrofy" / "lobes")

    result = hybrid_search(
        query=description,
        db_path=str(db_path),
        embedding=embedding,
        top_k=top_k,
        config_embed_model=config.embedding_model,
        lobe_dir=lobe_dir,
    )
    return [TextContent(type="text", text=_format_plan_json(result))]


def _handle_tasks(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent

    description: str = arguments.get("description", "")
    top_k: int = int(arguments.get("top_k", 10))

    root = _find_repo_root(Path.cwd())
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _make_error_content("Index not found. Run 'cerebrofy build' first.")

    from cerebrofy.config.loader import load_config
    from cerebrofy.search.hybrid import _embed_query, hybrid_search
    from cerebrofy.commands.tasks import _build_task_items

    config = load_config(root / ".cerebrofy" / "config.yaml")
    embedding = _embed_query(description, config)
    lobe_dir = str(root / ".cerebrofy" / "lobes")

    result = hybrid_search(
        query=description,
        db_path=str(db_path),
        embedding=embedding,
        top_k=top_k,
        config_embed_model=config.embedding_model,
        lobe_dir=lobe_dir,
    )
    items, _ = _build_task_items(result)
    tasks_list = [
        {
            "number": item.index,
            "neuron_name": item.neuron.name,
            "neuron_file": item.neuron.file,
            "line": item.neuron.start_line,
            "lobe": item.lobe_name,
            "blast_count": item.blast_count,
            "similarity": round(item.neuron.similarity, 3),
        }
        for item in items
    ]
    return [TextContent(type="text", text=json.dumps({"tasks": tasks_list}, indent=2))]


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

    _FEATURE_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Natural-language description of the feature"},
            "top_k": {"type": "integer", "description": "Number of results (default: 10)", "default": 10, "minimum": 1, "maximum": 100},
        },
        "required": ["description"],
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
                "List all indexed lobes (modules/packages) with neuron counts and summary paths. "
                "Use for high-level orientation before searching."
            ), inputSchema=_EMPTY),
            Tool(name="plan", description=(
                "Analyse which parts of the codebase are affected by a feature. "
                "Returns matched Neurons, blast radius, and affected lobes. Zero network calls."
            ), inputSchema=_FEATURE_SCHEMA),
            Tool(name="tasks", description=(
                "Generate a numbered implementation task list for a feature. "
                "Each task identifies the exact code unit, module, and structural risk."
            ), inputSchema=_FEATURE_SCHEMA),
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
        try:
            if name == "search_code":
                return _handle_search_code(args)
            elif name == "get_neuron":
                return _handle_get_neuron(args)
            elif name == "list_lobes":
                return _handle_list_lobes(args)
            elif name == "plan":
                return _handle_plan(args)
            elif name == "tasks":
                return _handle_tasks(args)
            elif name == "cerebrofy_build":
                return _handle_build(args)
            elif name == "cerebrofy_update":
                return _handle_update(args)
            elif name == "cerebrofy_validate":
                return _handle_validate(args)
            else:
                return _make_error_content(f"Unknown tool: {name}")
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
