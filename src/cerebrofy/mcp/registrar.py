"""MCP server registration: path detection, idempotent write, fallback snippet."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MCP_ENTRY: dict = {  # type: ignore[type-arg]
    "command": "cerebrofy",
    "args": ["mcp"],
    "env": {},
}

MCP_FALLBACK_SNIPPET: str = json.dumps(
    {"mcpServers": {"cerebrofy": MCP_ENTRY}},
    indent=2,
)

# Priority-ordered list of (tool_name, config_path) tuples.
# Paths use expanduser(); Windows paths guarded against missing env vars.
MCP_CONFIG_PATHS: list[tuple[str, Path]] = [
    (
        "Claude Desktop (macOS)",
        Path("~/Library/Application Support/Claude/claude_desktop_config.json").expanduser(),
    ),
    (
        "Claude Desktop (Windows)",
        Path(os.environ.get("APPDATA", "") + "/Claude/claude_desktop_config.json")
        if os.environ.get("APPDATA")
        else Path(""),
    ),
    (
        "Cursor (macOS/Linux)",
        Path("~/.cursor/mcp.json").expanduser(),
    ),
    (
        "Cursor (Windows)",
        Path(os.environ.get("USERPROFILE", "") + "/.cursor/mcp.json")
        if os.environ.get("USERPROFILE")
        else Path(""),
    ),
    (
        "Opencode",
        Path("~/.config/opencode/mcp.json").expanduser(),
    ),
    (
        "Generic MCP",
        Path("~/.config/mcp/servers.json").expanduser(),
    ),
]


def find_writable_mcp_path(global_mode: bool) -> Path | None:
    """Return the first writable MCP config path, or None if none found."""
    if global_mode:
        p = Path("~/.config/mcp/servers.json").expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    for _tool_name, path in MCP_CONFIG_PATHS:
        if not path or not path.name:
            continue
        if path.exists() and os.access(path, os.W_OK):
            return path
        if path.parent.exists() and os.access(path.parent, os.W_OK):
            return path

    # Fallback: create ~/.config/mcp/ and return the generic path.
    fallback = Path("~/.config/mcp/servers.json").expanduser()
    try:
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback
    except OSError:
        return None


def has_cerebrofy_mcp_entry(config_path: Path) -> bool:
    """Return True if mcpServers.cerebrofy key is already present in the config."""
    if not config_path.exists():
        return False
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return bool(data.get("mcpServers", {}).get("cerebrofy"))
    except (json.JSONDecodeError, OSError):
        return False


def write_mcp_entry(config_path: Path) -> None:
    """Merge cerebrofy MCP entry into config_path atomically."""
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    data.setdefault("mcpServers", {})["cerebrofy"] = MCP_ENTRY

    tmp_fd, tmp_path = tempfile.mkstemp(dir=config_path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, config_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def register_mcp(global_mode: bool) -> tuple[bool, str]:
    """Register the cerebrofy MCP entry. Returns (success, message)."""
    path = find_writable_mcp_path(global_mode)
    if path is None:
        return False, MCP_FALLBACK_SNIPPET

    if has_cerebrofy_mcp_entry(path):
        return True, f"already registered at {path}"

    write_mcp_entry(path)
    return True, f"registered at {path}"
