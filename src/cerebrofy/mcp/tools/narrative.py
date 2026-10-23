"""MCP tool for Narrative Engine."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import CallToolResult

from cerebrofy.narrative.generator import generate_narrative
from cerebrofy.mcp.errors import mcp_error


def _find_cerebrofy_dir(root: Path) -> Path | None:
    """Find .cerebrofy directory."""
    dir_path = root / ".cerebrofy"
    if dir_path.exists():
        return dir_path
    return None


def _read_narrative(cerebrofy_dir: Path, section: str | None = None, era: int | None = None) -> str:
    """Read NARRATIVE.md content."""
    narrative_path = cerebrofy_dir / "NARRATIVE.md"
    if not narrative_path.exists():
        return "Narrative not generated yet. Run with update=true."

    content = narrative_path.read_text(encoding="utf-8")

    if era is not None:
        # Extract specific era
        lines = content.split("\n")
        in_era = False
        era_lines = []
        for line in lines:
            if line.startswith(f"## Era {era}:"):
                in_era = True
            elif line.startswith("## Era ") and in_era:
                break
            if in_era:
                era_lines.append(line)
        if era_lines:
            return "\n".join(era_lines)
        return f"Era {era} not found."

    if section and section != "all":
        # Extract specific section
        lines = content.split("\n")
        in_section = False
        section_lines = []
        section_map = {
            "eras": "## Era",
            "events": "## Significant Events",
            "dna": "## Architectural DNA",
            "trajectory": "## Where It's Going",
        }
        target = section_map.get(section)
        if target:
            for line in lines:
                if line.startswith(target):
                    in_section = True
                elif line.startswith("## ") and in_section:
                    break
                if in_section:
                    section_lines.append(line)
            if section_lines:
                return "\n".join(section_lines)

    return content


def handle_narrative(arguments: dict[str, object]) -> "CallToolResult":
    """Handle cerebrofy_narrative MCP tool call."""
    from mcp.types import TextContent

    root = Path.cwd()
    cerebrofy_dir = _find_cerebrofy_dir(root)

    if cerebrofy_dir is None:
        return mcp_error("[NO_INDEX] cerebrofy.db not found. Run 'cerebrofy build' first.")

    section: str = arguments.get("section", "all")  # type: ignore[assignment]
    update = bool(arguments.get("update", False))
    era: int | None = arguments.get("era")  # type: ignore[assignment]

    if update:
        try:
            _ = generate_narrative(cerebrofy_dir, force=True)
        except ValueError as e:
            if "INSUFFICIENT_HISTORY" in str(e):
                return mcp_error("[INSUFFICIENT_HISTORY] " + str(e))
            return mcp_error("[ERROR] " + str(e))
        except FileNotFoundError as e:
            return mcp_error("[NO_INDEX] " + str(e))

    narrative_markdown = _read_narrative(cerebrofy_dir, section, era)

    # Get last updated time
    narrative_path = cerebrofy_dir / "NARRATIVE.md"
    last_updated = int(narrative_path.stat().st_mtime) if narrative_path.exists() else 0

    # Count eras and events from the file
    era_count = 0
    event_count = 0
    if narrative_path.exists():
        content = narrative_path.read_text(encoding="utf-8")
        era_count = content.count("## Era ")
        event_count = content.count("| ") - 1  # rough count from table

    current_era: dict[str, object] = {}
    if era is not None and era > 0:
        # Try to build current era from file
        pass

    result = {
        "narrative_markdown": narrative_markdown,
        "era_count": era_count,
        "event_count": event_count,
        "last_updated": last_updated,
        "current_era": current_era if current_era else None,
    }

    return [TextContent(type="text", text=__import__("json").dumps(result, indent=2))]