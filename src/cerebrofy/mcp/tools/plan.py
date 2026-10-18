"""MCP handler for the cerebrofy_plan tool (Idea #12).

Input: ``description`` (required), ``format`` ('markdown' | 'json'), and
``dry_run`` (default true). The planner never writes files; ``dry_run=False``
only adds an execution-handoff summary to the Markdown output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _find_root(cwd: Path) -> Path:
    """Walk up from CWD searching for .cerebrofy/config.yaml."""
    current = cwd if cwd.is_dir() else cwd.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")


def _err(message: str) -> list[Any]:
    from mcp.types import TextContent
    return [TextContent(type="text", text=message)]


def handle_plan(arguments: dict[str, Any]) -> list[Any]:
    """Generate a refactoring plan for a natural-language description."""
    from mcp.types import TextContent

    from cerebrofy.config.loader import load_config
    from cerebrofy.planning.formatter import plan_to_json, plan_to_markdown
    from cerebrofy.planning.planner import NO_INDEX, PlanError, build_refactor_plan
    from cerebrofy.search.hybrid import embed_query

    description = str(arguments.get("description", "") or "").strip()
    if not description:
        return _err("[error] 'description' is required.")
    fmt = str(arguments.get("format", "markdown") or "markdown").lower()
    if fmt not in ("markdown", "json"):
        return _err("[error] 'format' must be 'markdown' or 'json'.")
    dry_run = bool(arguments.get("dry_run", True))

    try:
        root = _find_root(Path.cwd())
    except FileNotFoundError:
        return _err("NO_INDEX: could not find .cerebrofy directory")

    config_path = root / ".cerebrofy" / "config.yaml"
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err(f"[{NO_INDEX}] Index not found. Run 'cerebrofy build' first.")

    try:
        config = load_config(config_path)
        embedding = embed_query(description, config.embedding_model)
    except ValueError as exc:
        return _err(f"[error] {exc}")

    try:
        plan = build_refactor_plan(
            description=description,
            db_path=db_path,
            embedding=embedding,
            repo_root=root,
            config_path=config_path,
            dry_run=dry_run,
        )
    except PlanError as exc:
        return _err(f"[{exc.code}] {exc.message}")
    except ValueError as exc:
        return _err(f"[error] {exc}")

    text = plan_to_json(plan) if fmt == "json" else plan_to_markdown(plan)
    return [TextContent(type="text", text=text)]
