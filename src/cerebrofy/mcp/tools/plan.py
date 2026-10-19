"""MCP handler for the cerebrofy_plan tool (Idea #12).

Input: ``description`` (required), ``format`` ('markdown' | 'json'), and
``dry_run`` (default true). The planner never writes files; ``dry_run=False``
only adds an execution-handoff summary to the Markdown output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cerebrofy.mcp.errors import mcp_error as _err
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


def handle_plan(arguments: dict[str, Any]) -> list[Any]:
    """Generate a refactoring plan for a natural-language description."""
    from mcp.types import TextContent

    from cerebrofy.config.loader import load_config
    from cerebrofy.planning.formatter import plan_to_json, plan_to_markdown
    from cerebrofy.planning.planner import NO_INDEX, PlanError, build_refactor_plan
    from cerebrofy.search.hybrid import embed_query
    from cerebrofy.db.connection import open_db_readonly

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
        return _err(f"[{NO_INDEX}] could not find .cerebrofy directory")

    config_path = root / ".cerebrofy" / "config.yaml"
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err(f"[{NO_INDEX}] Index not found. Run 'cerebrofy build' first.")

    try:
        config = load_config(config_path)
        embedding = embed_query(description, config.embedding_model)
    except ValueError as exc:
        return _err(f"[error] {exc}")

    conn = open_db_readonly(db_path)
    try:
        try:
            plan = build_refactor_plan(
                description=description,
                conn=conn,
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
    finally:
        conn.close()