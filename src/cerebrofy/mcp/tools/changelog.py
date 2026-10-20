"""MCP handler for the cerebrofy_changelog tool (Idea #14)."""

from __future__ import annotations

import json
import sqlite3
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


def handle_changelog(arguments: dict[str, Any]) -> list[Any]:
    """Generate a semantic changelog for a git range.

    Input: {since (required), audience?, format?}
    Output: the spec output schema —
      since, until, entries[], breaking_changes[], health_delta, full_text.

    Error codes: NO_INDEX (no index), REF_NOT_FOUND (unknown git ref).
    """
    from mcp.types import TextContent

    since = str(arguments.get("since") or "").strip()
    if not since:
        return _err(
            "[error] 'since' is required — a git tag, commit hash, "
            "'last-build', or 'project-start'."
        )

    audience = str(arguments.get("audience") or "developer")
    fmt = str(arguments.get("format") or "markdown")
    if audience not in ("developer", "pm", "user"):
        return _err(f"[error] Invalid audience '{audience}'. Choose from: developer, pm, user.")
    if fmt not in ("markdown", "github", "slack"):
        return _err(f"[error] Invalid format '{fmt}'. Choose from: markdown, github, slack.")

    try:
        root = _find_root(Path.cwd())
    except Exception:
        return _err(
            "[NO_INDEX] No .cerebrofy directory found. "
            "Run 'cerebrofy init' and 'cerebrofy build' first."
        )

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err("[NO_INDEX] Index not found. Run 'cerebrofy build' first.")

    try:
        from cerebrofy.changelog.classifier import ChangelogError
        from cerebrofy.changelog.generator import generate_changelog

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            report = generate_changelog(
                root, since, audience=audience, output_format=fmt, conn=conn
            )
        finally:
            conn.close()
    except ChangelogError as exc:
        return _err(f"[{exc.code}] {exc.message}")
    except ValueError as exc:
        return _err(f"[error] {exc}")
    except Exception as exc:
        return _err(f"cerebrofy_changelog failed: {exc}")

    return [TextContent(type="text", text=json.dumps(report.to_dict(), indent=2))]
