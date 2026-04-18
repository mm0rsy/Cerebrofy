"""MCP stdio server for cerebrofy — exposes build, update, validate as MCP tools."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any


def _find_repo_root(start: Path) -> Path:
    """Walk up from start searching for .cerebrofy/config.yaml.

    Raises FileNotFoundError if not found at filesystem root.
    """
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    raise FileNotFoundError(
        "No Cerebrofy config found in current directory or any parent. "
        "Run 'cerebrofy init' first."
    )


def _run_cerebrofy(args: list[str], cwd: str, timeout: int = 300) -> tuple[int, str]:
    """Run ``cerebrofy <args>`` in *cwd*. Returns (returncode, combined output)."""
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
    """Return a TextContent list for MCP error responses."""
    from mcp.types import TextContent
    return [TextContent(type="text", text=message)]


def _handle_build(arguments: dict[str, Any]) -> list[Any]:
    """Trigger a full atomic re-index and return status as TextContent."""
    from mcp.types import TextContent

    try:
        root = _find_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}\nRun 'cerebrofy init' to set up the repository.")
    code, output = _run_cerebrofy(["build"], str(root))
    status = "success" if code == 0 else "error"
    return [TextContent(type="text", text=f"[{status}]\n{output}")]


def _handle_update(arguments: dict[str, Any]) -> list[Any]:
    """Trigger a partial re-index and return status as TextContent."""
    from mcp.types import TextContent

    try:
        root = _find_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}\nRun 'cerebrofy init' to set up the repository.")
    path: str | None = arguments.get("path")
    cmd = ["update", path] if path else ["update"]
    code, output = _run_cerebrofy(cmd, str(root))
    status = "success" if code == 0 else "error"
    return [TextContent(type="text", text=f"[{status}]\n{output}")]


def _handle_validate(arguments: dict[str, Any]) -> list[Any]:
    """Run drift validation and return status as TextContent."""
    from mcp.types import TextContent

    try:
        root = _find_repo_root(Path.cwd())
    except FileNotFoundError as exc:
        return _make_error_content(f"[error] {exc}\nRun 'cerebrofy init' to set up the repository.")
    code, output = _run_cerebrofy(["validate"], str(root))
    drift_label = {0: "clean", 1: "minor_drift", 2: "structural_drift"}.get(code, "error")
    return [TextContent(type="text", text=f"[{drift_label}]\n{output}")]


async def run_mcp_server() -> None:
    """Start the cerebrofy MCP stdio server."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    app = Server("cerebrofy")

    _EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    _PATH_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Specific file path to re-index (omit to auto-detect changed files)",
            }
        },
    }

    @app.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="cerebrofy_build",
                description=(
                    "Full atomic re-index of the entire repository. "
                    "Use when the index is missing or fundamentally out of date. "
                    "Takes longer than update; prefer cerebrofy_update for incremental changes."
                ),
                inputSchema=_EMPTY_SCHEMA,
            ),
            Tool(
                name="cerebrofy_update",
                description=(
                    "Partial re-index of changed files (auto-detected via git diff or hash comparison). "
                    "Pass 'path' to limit to a specific file. Preferred for day-to-day sync."
                ),
                inputSchema=_PATH_SCHEMA,
            ),
            Tool(
                name="cerebrofy_validate",
                description=(
                    "Check for drift between the current source and the index. "
                    "Returns 'clean', 'minor_drift', or 'structural_drift'. "
                    "Makes zero writes — safe to call at any time."
                ),
                inputSchema=_EMPTY_SCHEMA,
            ),
        ]

    @app.call_tool()  # type: ignore[no-untyped-call,untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "cerebrofy_build":
                return _handle_build(arguments or {})
            elif name == "cerebrofy_update":
                return _handle_update(arguments or {})
            elif name == "cerebrofy_validate":
                return _handle_validate(arguments or {})
            else:
                return _make_error_content(f"Unknown tool: {name}")
        except FileNotFoundError as exc:
            return _make_error_content(
                f"[error] {exc}\nRun 'cerebrofy init' to set up the repository."
            )
        except subprocess.TimeoutExpired:
            return _make_error_content(
                "[error] Command timed out after 300 seconds."
            )
        except Exception as exc:
            print(f"cerebrofy mcp: unexpected error: {exc}", file=sys.stderr)
            return _make_error_content(f"[error] {exc}")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())



def _find_repo_root(start: Path) -> Path:
    """Walk up from start searching for .cerebrofy/config.yaml.

    Raises FileNotFoundError if not found at filesystem root.
    """
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    raise FileNotFoundError(
        "No Cerebrofy config found in current directory or any parent. "
        "Run 'cerebrofy init' first."
    )


def _make_error_content(message: str) -> list[Any]:
    """Return a TextContent list with isError=True for MCP error responses."""
    from mcp.types import TextContent
    return [TextContent(type="text", text=message)]


def _make_error_result(message: str) -> list[Any]:
    """Build an error CallToolResult-compatible list."""
    return _make_error_content(message)


def _handle_plan(arguments: dict[str, Any]) -> list[Any]:
    """Run hybrid search and return plan JSON as TextContent."""
    from mcp.types import TextContent

    description: str = arguments.get("description", "")
    top_k_arg: int | None = arguments.get("top_k")

    root = _find_repo_root(Path.cwd())
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    from cerebrofy.config.loader import load_config
    from cerebrofy.db.connection import check_schema_version
    import sqlite3

    config = load_config(root / ".cerebrofy" / "config.yaml")
    effective_top_k = top_k_arg or config.top_k or 10

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        check_schema_version(conn)
    except ValueError as exc:
        conn.close()
        raise exc
    conn.close()

    from cerebrofy.search.hybrid import _embed_query, hybrid_search
    from cerebrofy.commands.plan import _format_plan_json

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
    return [TextContent(type="text", text=_format_plan_json(result))]


def _handle_tasks(arguments: dict[str, Any]) -> list[Any]:
    """Run hybrid search and return structured tasks JSON as TextContent."""
    from mcp.types import TextContent

    description: str = arguments.get("description", "")
    top_k_arg: int | None = arguments.get("top_k")

    root = _find_repo_root(Path.cwd())
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    from cerebrofy.config.loader import load_config
    from cerebrofy.db.connection import check_schema_version
    import sqlite3

    config = load_config(root / ".cerebrofy" / "config.yaml")
    effective_top_k = top_k_arg or config.top_k or 10

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        check_schema_version(conn)
    except ValueError as exc:
        conn.close()
        raise exc
    conn.close()

    from cerebrofy.search.hybrid import _embed_query, hybrid_search
    from cerebrofy.commands.tasks import _build_task_items

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

    items, _ = _build_task_items(result)
    tasks_list = [
        {
            "number": item.index,
            "neuron_name": item.neuron.name,
            "neuron_file": item.neuron.file,
            "lobe": item.lobe_name,
            "blast_count": item.blast_count,
            "similarity": round(item.neuron.similarity, 3),
        }
        for item in items
    ]
    return [TextContent(type="text", text=json.dumps({"tasks": tasks_list}, indent=2))]


def _handle_specify(arguments: dict[str, Any]) -> list[Any]:
    """Run hybrid search + LLM and return spec file path + content as TextContent."""
    from mcp.types import TextContent

    description: str = arguments.get("description", "")
    top_k_arg: int | None = arguments.get("top_k")

    root = _find_repo_root(Path.cwd())
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    from cerebrofy.config.loader import load_config
    from cerebrofy.db.connection import check_schema_version
    import sqlite3

    config = load_config(root / ".cerebrofy" / "config.yaml")
    effective_top_k = top_k_arg or config.top_k or 10

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        check_schema_version(conn)
        meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
        db_meta = {row[0]: row[1] for row in meta_rows}
    except ValueError:
        conn.close()
        raise
    else:
        conn.close()

    from cerebrofy.commands.specify import _validate_specify_prerequisites
    _validate_specify_prerequisites(config, db_meta)

    import os
    from cerebrofy.search.hybrid import _embed_query, hybrid_search
    from cerebrofy.llm.prompt_builder import build_llm_context
    from cerebrofy.llm.client import LLMClient
    from datetime import datetime
    from cerebrofy.commands.specify import _resolve_output_path

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
        return [TextContent(type="text", text="No relevant code units found for this description.")]

    payload = build_llm_context(result, config.system_prompt_template or None, str(root))

    if "openai" in config.llm_endpoint.lower():
        api_key = os.environ.get("OPENAI_API_KEY", "")
    else:
        api_key = os.environ.get("LLM_API_KEY", "")

    client = LLMClient(
        base_url=config.llm_endpoint,
        api_key=api_key,
        model=config.llm_model,
        timeout=config.llm_timeout,
    )

    full_response = client.call(payload)

    specs_dir = root / "docs" / "cerebrofy" / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    output_path = _resolve_output_path(specs_dir, datetime.now())
    output_path.write_text(full_response, encoding="utf-8")

    rel_path = str(output_path.relative_to(root))
    return [TextContent(type="text", text=json.dumps({
        "output_file": rel_path,
        "content": full_response,
    }, indent=2))]


async def run_mcp_server() -> None:
    """Start the cerebrofy MCP stdio server."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    app = Server("cerebrofy")

    _TOOL_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Natural-language description of the feature or change",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of KNN search results (default: 10, range: 1–100)",
                "minimum": 1,
                "maximum": 100,
                "default": 10,
            },
        },
        "required": ["description"],
    }

    @app.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]  # mcp has no stubs
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="plan",
                description=(
                    "Analyze which parts of the codebase would be affected by a feature. "
                    "Returns matched Neurons, blast radius, affected lobes, and re-index scope. "
                    "Makes zero network calls — safe offline and in CI."
                ),
                inputSchema=_TOOL_SCHEMA,
            ),
            Tool(
                name="tasks",
                description=(
                    "Generate a numbered implementation task list for a feature. "
                    "Each task identifies the exact code unit to modify, its module, and structural risk. "
                    "Makes zero network calls — safe offline and in CI."
                ),
                inputSchema=_TOOL_SCHEMA,
            ),
            Tool(
                name="specify",
                description=(
                    "Generate an AI-grounded feature specification using the codebase as context. "
                    "The spec is written to docs/cerebrofy/specs/ and the full content is returned. "
                    "Requires an LLM endpoint configured in .cerebrofy/config.yaml."
                ),
                inputSchema=_TOOL_SCHEMA,
            ),
        ]

    @app.call_tool()  # type: ignore[no-untyped-call,untyped-decorator]  # mcp has no stubs
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        schema_mismatch_msg = "Schema version mismatch. Run 'cerebrofy migrate' to update."
        embed_mismatch_msg = "Embedding model mismatch. Run 'cerebrofy build' to rebuild."
        no_config_msg = "No Cerebrofy index found. Run 'cerebrofy build' first."

        try:
            if name == "plan":
                return _handle_plan(arguments)
            elif name == "tasks":
                return _handle_tasks(arguments)
            elif name == "specify":
                return _handle_specify(arguments)
            else:
                return _make_error_content(f"Unknown tool: {name}")
        except FileNotFoundError:
            return _make_error_content(no_config_msg)
        except ValueError as exc:
            msg = str(exc)
            if "schema" in msg.lower():
                return _make_error_content(schema_mismatch_msg)
            if "embedding" in msg.lower() or "embed" in msg.lower():
                return _make_error_content(embed_mismatch_msg)
            return _make_error_content(f"Error: {msg}")
        except TimeoutError:
            return _make_error_content(
                "LLM request timed out. Increase 'llm_timeout' in config.yaml."
            )
        except Exception as exc:
            print(f"cerebrofy mcp: unexpected error: {exc}", file=sys.stderr)
            return _make_error_content(f"Error: {exc}")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
