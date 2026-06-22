"""MCP handlers for the Phase 2 causal memory graph tools.

Kept in a separate module per the mcp/tools/ pattern so each tool family
has its own file rather than growing server.py unboundedly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _find_root(cwd: Path) -> Path:
    current = cwd if cwd.is_dir() else cwd.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")


def _err(message: str) -> list[Any]:
    from mcp.types import TextContent
    return [TextContent(type="text", text=message)]


def handle_link_memories(arguments: dict[str, Any]) -> list[Any]:
    from_id = arguments.get("from_memory", "").strip()
    to_id = arguments.get("to_memory", "").strip()
    rel_type = arguments.get("rel_type", "").strip()

    if not from_id or not to_id or not rel_type:
        return _err(
            "cerebrofy_link_memories: 'from_memory', 'to_memory', and 'rel_type' are required"
        )

    from cerebrofy.memory.store import VALID_REL_TYPES
    if rel_type not in VALID_REL_TYPES:
        return _err(
            f"cerebrofy_link_memories: invalid rel_type '{rel_type}'. "
            f"Valid: {', '.join(sorted(VALID_REL_TYPES))}"
        )

    try:
        root = _find_root(Path.cwd())
    except Exception:
        return _err("NO_INDEX: could not find .cerebrofy directory")

    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return _err("NO_INDEX: run cerebrofy build first")

    try:
        from mcp.types import TextContent
        from cerebrofy.memory.store import MemoryEdge, get_memory, open_memories_db, write_memory_edge

        conn = open_memories_db(cerebrofy_dir)
        try:
            if not get_memory(conn, from_id):
                return _err(f"cerebrofy_link_memories: from_memory '{from_id}' not found")
            if not get_memory(conn, to_id):
                return _err(f"cerebrofy_link_memories: to_memory '{to_id}' not found")
            edge = MemoryEdge(
                from_memory_id=from_id, to_memory_id=to_id,
                rel_type=rel_type, created_ts=int(time.time()),
                author=arguments.get("author") or "agent:unknown",
            )
            write_memory_edge(conn, edge)
            conn.commit()
        finally:
            conn.close()

        return [TextContent(type="text", text=json.dumps(
            {"from_memory": from_id, "to_memory": to_id, "rel_type": rel_type}, indent=2
        ))]
    except Exception as exc:
        return _err(f"cerebrofy_link_memories failed: {exc}")


def handle_trace_history(arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent

    memory_id = arguments.get("memory", "").strip()
    if not memory_id:
        return _err("cerebrofy_trace_history: 'memory' is required")

    depth = int(arguments.get("depth", 5))

    try:
        root = _find_root(Path.cwd())
    except Exception:
        return [TextContent(type="text", text=json.dumps({"chain": [], "count": 0}))]

    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return [TextContent(type="text", text=json.dumps({"chain": [], "count": 0}))]

    try:
        from cerebrofy.memory.store import open_memories_db, trace_history

        conn = open_memories_db(cerebrofy_dir)
        try:
            chain = trace_history(conn, memory_id, depth=depth)
        finally:
            conn.close()

        out = {
            "chain": [
                {
                    "id": m.id, "type": m.type, "title": m.title, "body": m.body,
                    "neuron": m.neuron_id, "lobe": m.lobe, "author": m.author,
                    "created_ts": m.created_ts, "tags": list(m.tags),
                    "decay_score": m.decay_score, "status": m.status,
                }
                for m in chain
            ],
            "count": len(chain),
        }
        return [TextContent(type="text", text=json.dumps(out, indent=2))]
    except Exception as exc:
        return [TextContent(type="text", text=json.dumps({"chain": [], "error": str(exc)}))]
