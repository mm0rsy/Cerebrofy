"""Project-wide constants for Cerebrofy subprocesses.

Dependency-free — safe to import from anywhere (config parsing, errors, the
CLI) without risking import cycles.
"""

from __future__ import annotations

# Timeout (seconds) for git subprocess invocations used by index/update and
# changelog range resolution.
DEFAULT_GIT_TIMEOUT_SECONDS: int = 15

# Timeout (seconds) for a single MCP tool command execution.
DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS: int = 300
