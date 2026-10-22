"""Shared limits for multi-agent coordination (Idea #25)."""

from __future__ import annotations

#: Default claim lifetime exposed by the CLI and MCP tools.
DEFAULT_TTL_MINUTES = 60

#: Hard ceiling for a claim lifetime (24 hours).
MAX_TTL_MINUTES = 1440

#: Default heartbeat interval; agents idle for two intervals are stale.
HEARTBEAT_INTERVAL_SECONDS = 300

#: Canonical memory-conflict resolution strategies (single source of truth).
RESOLUTION_OPTIONS: tuple[str, ...] = (
    "keep_newest",
    "keep_by_author",
    "human_review",
    "merge",
)
