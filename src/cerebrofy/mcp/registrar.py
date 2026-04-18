"""MCP server registration: path detection, idempotent write, fallback snippet."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MCP_ENTRY: dict = {  # type: ignore[type-arg]
    "command": "python",
    "args": ["-m", "cerebrofy", "mcp"],
    "env": {},
}

MCP_FALLBACK_SNIPPET: str = json.dumps(
    {"mcpServers": {"cerebrofy": MCP_ENTRY}},
    indent=2,
)

# Priority-ordered list of (tool_name, config_path) tuples.
# Paths use expanduser(); Windows paths guarded against missing env vars.
# Canonical name per Phase 5 spec (T033 / FR-012). 7-path priority list.
MCP_CONFIG_PRIORITY_LIST: list[Path] = [
    Path("~/Library/Application Support/Claude/claude_desktop_config.json").expanduser(),
    Path(os.environ.get("APPDATA", "") + "/Claude/claude_desktop_config.json")
    if os.environ.get("APPDATA") else Path(""),
    Path("~/.cursor/mcp.json").expanduser(),
    Path(os.environ.get("USERPROFILE", "") + "/.cursor/mcp.json")
    if os.environ.get("USERPROFILE") else Path(""),
    Path("~/.config/opencode/mcp.json").expanduser(),
    Path("~/.config/mcp/servers.json").expanduser(),
    Path("~/.config/mcp/servers.json").expanduser(),  # fallback (same as generic MCP)
]

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


def find_writable_mcp_config() -> Path:
    """Return the first writable MCP config path from MCP_CONFIG_PRIORITY_LIST.

    Creates the fallback path's parent directory if no existing writable path is found.
    """
    for path in MCP_CONFIG_PRIORITY_LIST:
        if not path or not path.name:
            continue
        if path.exists() and os.access(path, os.W_OK):
            return path
        if path.parent.exists() and os.access(path.parent, os.W_OK):
            return path

    fallback = Path("~/.config/mcp/servers.json").expanduser()
    fallback.parent.mkdir(parents=True, exist_ok=True)
    return fallback


def read_mcp_config(config_path: Path) -> dict:  # type: ignore[type-arg]
    """Read and parse JSON from config_path; returns empty dict if absent or malformed."""
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return {}


def detect_multiple_installations() -> list[str]:
    """Return all cerebrofy binary paths found on PATH (via which/where)."""
    import shutil
    import subprocess

    paths: list[str] = []
    if shutil.which("cerebrofy") is None:
        return paths

    try:
        if os.name == "nt":
            result = subprocess.run(
                ["where", "cerebrofy"], capture_output=True, text=True, timeout=5
            )
        else:
            result = subprocess.run(
                ["which", "-a", "cerebrofy"], capture_output=True, text=True, timeout=5
            )
        if result.returncode == 0:
            paths = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return paths


def warn_if_multiple_installations() -> None:
    """Print a warning if more than one cerebrofy binary is found on PATH (FR-018)."""
    paths = detect_multiple_installations()
    if len(paths) <= 1:
        return
    print("Warning: Multiple Cerebrofy installations detected.")
    for p in paths:
        print(f"  {p}")
    print("To fix: remove the older installation or update the MCP entry manually.")
