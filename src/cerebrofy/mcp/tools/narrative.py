"""MCP tool for Narrative Engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cerebrofy.mcp.errors import mcp_error
from cerebrofy.narrative.generator import (
    NarrativeData,
    build_narrative_data,
    era_to_dict,
    generate_narrative,
)

_SECTION_TARGETS = {
    "events": "## Significant Events",
    "dna": "## Architectural DNA",
    "trajectory": "## Where It's Going",
}


def _find_cerebrofy_dir(root: Path) -> Path | None:
    """Find .cerebrofy directory."""
    dir_path = root / ".cerebrofy"
    if dir_path.exists():
        return dir_path
    return None


def _extract_era(content: str, era: int) -> str | None:
    """Return one ``## Era N`` section (heading through the next H2)."""
    lines = content.split("\n")
    in_era = False
    era_lines: list[str] = []
    for line in lines:
        if line.startswith(f"## Era {era}:") or line.startswith(f"## Era {era} "):
            in_era = True
        elif line.startswith("## ") and in_era:
            break
        if in_era:
            era_lines.append(line)
    return "\n".join(era_lines) if era_lines else None


def _extract_all_eras(content: str) -> str | None:
    """Return every ``## Era`` section, skipping the non-era H2 sections."""
    lines = content.split("\n")
    in_era = False
    era_lines: list[str] = []
    for line in lines:
        if line.startswith("## Era "):
            in_era = True
        elif line.startswith("## ") and in_era:
            in_era = False
        if in_era:
            era_lines.append(line)
    return "\n".join(era_lines) if era_lines else None


def _extract_section(content: str, heading: str) -> str | None:
    lines = content.split("\n")
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        if line.startswith(heading):
            in_section = True
        elif line.startswith("## ") and in_section:
            break
        if in_section:
            section_lines.append(line)
    return "\n".join(section_lines) if section_lines else None


def _read_narrative(
    cerebrofy_dir: Path, section: str | None = None, era: int | None = None
) -> str:
    """Read NARRATIVE.md, optionally narrowed to an era or section."""
    narrative_path = cerebrofy_dir / "NARRATIVE.md"
    if not narrative_path.exists():
        return "Narrative not generated yet. Run with update=true."

    content = narrative_path.read_text(encoding="utf-8")

    if era is not None:
        return _extract_era(content, era) or f"Era {era} not found."

    if section and section != "all":
        if section == "eras":
            return _extract_all_eras(content) or content
        target = _SECTION_TARGETS.get(section)
        if target:
            return _extract_section(content, target) or content

    return content


def _current_era(data: NarrativeData, era: int | None) -> dict[str, object] | None:
    """Latest era, or the explicitly requested (1-indexed) era."""
    if not data.eras:
        return None
    if era is not None and 1 <= era <= len(data.eras):
        return era_to_dict(data.eras[era - 1])
    return era_to_dict(data.eras[-1])


def handle_narrative(arguments: dict[str, object]) -> list[Any]:
    """Handle cerebrofy_narrative MCP tool call."""
    from mcp.types import TextContent

    root = Path.cwd()
    cerebrofy_dir = _find_cerebrofy_dir(root)

    if cerebrofy_dir is None:
        return mcp_error("[NO_INDEX] cerebrofy.db not found. Run 'cerebrofy build' first.")

    section = str(arguments.get("section") or "all")
    update = bool(arguments.get("update", False))
    raw_era = arguments.get("era")
    era = raw_era if isinstance(raw_era, int) else None

    if update:
        try:
            _ = generate_narrative(cerebrofy_dir, force=True)
        except ValueError as exc:
            if "INSUFFICIENT_HISTORY" in str(exc):
                return mcp_error("[INSUFFICIENT_HISTORY] " + str(exc))
            return mcp_error("[ERROR] " + str(exc))
        except FileNotFoundError as exc:
            return mcp_error("[NO_INDEX] " + str(exc))

    try:
        data = build_narrative_data(cerebrofy_dir)
    except FileNotFoundError as exc:
        return mcp_error("[NO_INDEX] " + str(exc))
    except Exception as exc:  # noqa: BLE001 — return a structured MCP error
        return mcp_error("[ERROR] " + str(exc))

    narrative_markdown = _read_narrative(cerebrofy_dir, section, era)

    narrative_path = cerebrofy_dir / "NARRATIVE.md"
    last_updated = (
        int(narrative_path.stat().st_mtime)
        if narrative_path.exists()
        else data.last_updated
    )

    result = {
        "narrative_markdown": narrative_markdown,
        "era_count": data.era_count,
        "event_count": data.event_count,
        "last_updated": last_updated,
        "current_era": _current_era(data, era),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]
