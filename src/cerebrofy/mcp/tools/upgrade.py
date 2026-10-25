"""MCP handler for the cerebrofy_upgrade tool (Idea #19)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from cerebrofy.mcp.errors import mcp_error as _err
from cerebrofy.utils.paths import find_repo_root as _find_repo_root_impl


def _find_root(cwd: Path) -> Path:
    root = _find_repo_root_impl(cwd)
    if root is None:
        raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")
    return root


def _coerce_steps(raw: object) -> list[int] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("'step' must be an array of integers.")
    steps: list[int] = []
    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'step' must contain integers, got {item!r}.") from exc
        if value <= 0:
            raise ValueError("'step' values must be positive integers.")
        if value not in steps:
            steps.append(value)
    return steps or None


def handle_upgrade(arguments: dict[str, Any]) -> list[Any]:
    """Plan / auto-fix / validate a dependency upgrade.

    Input: package (required), from_version?, to_version?, breaking_only?,
    auto_fix?, step?, validate?, format?.

    Error codes: NO_INDEX, PACKAGE_NOT_USED, MANIFEST_NOT_FOUND,
    VERSION_NOT_FOUND.
    """
    from mcp.types import TextContent

    package = str(arguments.get("package") or "").strip()
    if not package:
        return _err("[error] 'package' is required (e.g. 'pydantic').")

    fmt = str(arguments.get("format") or "markdown")
    if fmt not in ("markdown", "json"):
        return _err(f"[error] Invalid format '{fmt}'. Choose from: markdown, json.")

    from_version = (
        str(arguments["from_version"]).strip()
        if arguments.get("from_version") is not None
        else None
    )
    to_version = (
        str(arguments["to_version"]).strip()
        if arguments.get("to_version") is not None
        else None
    )
    breaking_only = bool(arguments.get("breaking_only", True))
    auto_fix = bool(arguments.get("auto_fix", False))
    validate = bool(arguments.get("validate", False))
    try:
        steps = _coerce_steps(arguments.get("step"))
    except ValueError as exc:
        return _err(f"[error] {exc}")

    try:
        root = _find_root(Path.cwd())
    except Exception:  # noqa: BLE001
        return _err(
            "[NO_INDEX] No .cerebrofy directory found. "
            "Run 'cerebrofy init' and 'cerebrofy build' first."
        )

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err("[NO_INDEX] Index not found. Run 'cerebrofy build' first.")

    from cerebrofy.upgrade.fixer import FixerError, apply_fixes
    from cerebrofy.upgrade.manifest import ManifestError, find_manifest
    from cerebrofy.upgrade.planner import build_plan, render_markdown
    from cerebrofy.upgrade.scanner import scan_package
    from cerebrofy.upgrade.validator import validate_upgrade

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        try:
            manifest = find_manifest(
                package,
                from_version,
                to_version,
                extra_dirs=(root / ".cerebrofy" / "upgrades",),
            )
        except ManifestError as exc:
            return _err(f"[{exc.code}] {exc.message}")

        if validate and not auto_fix:
            validation_only = validate_upgrade(manifest, conn, root)
            if fmt == "json":
                return [
                    TextContent(type="text", text=json.dumps(validation_only.to_dict(), indent=2))
                ]
            return [TextContent(type="text", text=validation_only.to_markdown())]

        scan = scan_package(package, manifest, conn, root)
        try:
            scan.require_used()
        except ManifestError as exc:
            return _err(f"[{exc.code}] {exc.message}")

        plan = build_plan(package, manifest, scan, conn, breaking_only=breaking_only)
        fixes: list[Any] = []
        validation: Any = None
        if auto_fix:
            try:
                fixes = apply_fixes(plan, manifest, scan, root, steps)
            except FixerError as exc:
                return _err(f"[{exc.code}] {exc.message}")
            if validate:
                validation = validate_upgrade(manifest, conn, root)
    except ValueError as exc:
        return _err(f"[error] {exc}")
    except Exception as exc:  # noqa: BLE001
        return _err(f"cerebrofy_upgrade failed: {exc}")
    finally:
        conn.close()

    if fmt == "json":
        payload = plan.to_dict()
        payload["auto_fix_results"] = [fix.to_dict() for fix in fixes]
        if validation is not None:
            payload["validation"] = validation.to_dict()
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    return [TextContent(type="text", text=render_markdown(plan, validation=validation, fix_results=fixes))]
