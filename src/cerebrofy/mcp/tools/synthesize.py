"""MCP tool for Cross-Session Synthesizer."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import CallToolResult

from cerebrofy.synthesizer.analyzer import run_synthesis
from cerebrofy.mcp.errors import mcp_error


def _find_cerebrofy_dir(root: Path) -> Path | None:
    """Find .cerebrofy directory."""
    dir_path = root / ".cerebrofy"
    if dir_path.exists():
        return dir_path
    return None


def _read_patterns(
    cerebrofy_dir: Path,
    min_confidence: float,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Read synthesized patterns from memories table."""
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not memories_db.exists():
        return []

    conn = sqlite3.connect(memories_db)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE type = 'pattern' AND tags LIKE '%synthesized%'
            ORDER BY created_ts DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

        patterns = []
        for row in rows:
            tags = row["tags"].split(",") if row["tags"] else []
            p_type = next((t for t in tags if t != "synthesized"), "pattern")
            patterns.append(
                {
                    "type": p_type,
                    "title": row["title"],
                    "confidence": 0.7,  # Default; could parse from body
                    "body": row["body"],
                    "sessions_analyzed": 0,
                    "sample_size": 0,
                }
            )
        return [p for p in patterns if p["confidence"] >= min_confidence]
    finally:
        conn.close()


def handle_synthesize(arguments: dict[str, object]) -> "CallToolResult":
    """Handle cerebrofy_synthesize MCP tool call."""
    from mcp.types import TextContent

    root = Path.cwd()
    cerebrofy_dir = _find_cerebrofy_dir(root)

    if cerebrofy_dir is None:
        return mcp_error("[NO_INDEX] cerebrofy.db not found. Run 'cerebrofy build' first.")

    sessions_db = cerebrofy_dir / "db" / "sessions.db"
    if not sessions_db.exists():
        return mcp_error("[NO_SESSION_RECORDER] Session recording not enabled in cerebrofy.yaml.")

    run_now = bool(arguments.get("run_now", False))
    min_sessions = int(str(arguments.get("min_sessions", 10)))
    show_patterns = bool(arguments.get("show_patterns", True))
    min_confidence = float(str(arguments.get("min_confidence", 0.7)))

    if run_now:
        patterns = run_synthesis(cerebrofy_dir, min_sessions=min_sessions, min_confidence=min_confidence, run_now=True)
        patterns_found = len(patterns)
        patterns_written = len([p for p in patterns if p.confidence >= min_confidence])

        # Get next synthesis time
        import time
        next_synthesis_at = int(time.time()) + 86400  # placeholder

        if show_patterns:
            result = {
                "patterns_found": patterns_found,
                "patterns_written": patterns_written,
                "patterns": [
                    {
                        "type": p.type,
                        "title": p.title,
                        "confidence": p.confidence,
                        "body": p.body,
                        "sessions_analyzed": p.sessions_analyzed,
                        "sample_size": p.sample_size,
                    }
                    for p in patterns if p.confidence >= min_confidence
                ],
                "sessions_analyzed": patterns[0].sessions_analyzed if patterns else 0,
                "next_synthesis_at": next_synthesis_at,
            }
        else:
            result = {
                "patterns_found": patterns_found,
                "patterns_written": patterns_written,
                "patterns": [],
                "sessions_analyzed": patterns[0].sessions_analyzed if patterns else 0,
                "next_synthesis_at": next_synthesis_at,
            }
        return [TextContent(type="text", text=__import__("json").dumps(result, indent=2))]

    # Just read existing patterns
    _read_patterns(cerebrofy_dir, min_confidence)

    import time
    next_synthesis_at = int(time.time()) + 86400  # placeholder

    result = {
        "patterns_found": len(patterns),
        "patterns_written": 0,
        "patterns": patterns,
        "sessions_analyzed": 0,
        "next_synthesis_at": next_synthesis_at,
    }
    return [TextContent(type="text", text=__import__("json").dumps(result, indent=2))]