"""MCP tool for Cross-Session Synthesizer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cerebrofy.mcp.errors import mcp_error
from cerebrofy.memory.store import open_memories_db
from cerebrofy.synthesizer import (
    StoredPattern,
    list_synthesized_patterns,
    sessions_until_next_synthesis,
    synthesis_interval,
    synthesize,
)


def _find_cerebrofy_dir(root: Path) -> Path | None:
    """Find .cerebrofy directory."""
    dir_path = root / ".cerebrofy"
    if dir_path.exists():
        return dir_path
    return None


def _pattern_payload(pattern: StoredPattern) -> dict[str, object]:
    """Serialize a stored pattern for the MCP response."""
    return {
        "type": pattern.type,
        "title": pattern.title,
        "confidence": pattern.confidence,
        "body": pattern.body,
        "sessions_analyzed": pattern.sessions_analyzed,
        "sample_size": pattern.sample_size,
        "lobe": pattern.lobe,
    }


def _read_patterns(
    cerebrofy_dir: Path,
    min_confidence: float,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Read synthesized patterns from memories.db, filtering by confidence."""
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not memories_db.exists():
        return []

    conn = open_memories_db(cerebrofy_dir)
    try:
        patterns = list_synthesized_patterns(conn, limit=limit)
    finally:
        conn.close()
    return [
        _pattern_payload(pattern)
        for pattern in patterns
        if pattern.confidence >= min_confidence
    ]


def _next_run_payload(cerebrofy_dir: Path) -> dict[str, object]:
    """M5: report an honest countdown, never a fabricated timestamp."""
    every_n = synthesis_interval(cerebrofy_dir)
    return {
        "sessions_until_next_synthesis": sessions_until_next_synthesis(
            cerebrofy_dir, every_n
        ),
        "next_synthesis_at": None,
    }


def handle_synthesize(arguments: dict[str, object]) -> list[Any]:
    """Handle cerebrofy_synthesize MCP tool call."""
    from mcp.types import TextContent

    root = Path.cwd()
    cerebrofy_dir = _find_cerebrofy_dir(root)

    if cerebrofy_dir is None:
        return mcp_error("[NO_INDEX] cerebrofy.db not found. Run 'cerebrofy build' first.")

    sessions_db = cerebrofy_dir / "db" / "sessions.db"
    if not sessions_db.exists():
        return mcp_error(
            "[NO_SESSION_RECORDER] Session recording not enabled. "
            "Set 'record_sessions: true' in .cerebrofy/config.yaml."
        )

    run_now = bool(arguments.get("run_now", False))
    min_sessions = int(str(arguments.get("min_sessions", 10)))
    show_patterns = bool(arguments.get("show_patterns", True))
    min_confidence = float(str(arguments.get("min_confidence", 0.7)))

    next_run = _next_run_payload(cerebrofy_dir)

    if run_now:
        result = synthesize(
            cerebrofy_dir,
            min_sessions=min_sessions,
            min_confidence=min_confidence,
        )
        payloads = [
            {
                "type": pattern.type,
                "title": pattern.title,
                "confidence": pattern.confidence,
                "body": pattern.body,
                "sessions_analyzed": pattern.sessions_analyzed,
                "sample_size": pattern.sample_size,
                "lobe": pattern.lobe,
            }
            for pattern in result.patterns
            if pattern.confidence >= min_confidence
        ]
        response: dict[str, object] = {
            "patterns_found": len(result.patterns),
            "patterns_written": result.written,
            "patterns": payloads if show_patterns else [],
            "sessions_analyzed": result.sessions_analyzed,
            **next_run,
        }
        return [TextContent(type="text", text=json.dumps(response, indent=2))]

    # B1: read path must return the list it computed (no undefined name).
    patterns = _read_patterns(cerebrofy_dir, min_confidence)
    response = {
        "patterns_found": len(patterns),
        "patterns_written": 0,
        "patterns": patterns if show_patterns else [],
        "sessions_analyzed": max(
            (int(str(p.get("sessions_analyzed", 0))) for p in patterns), default=0
        ),
        **next_run,
    }
    return [TextContent(type="text", text=json.dumps(response, indent=2))]
