"""Data models and exception for the Live Agent Session Recorder (Idea #11).

All public names here are re-exported via the ``recorder.py`` facade so that
``from cerebrofy.session.recorder import SessionRecord`` etc. keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cerebrofy.errors import (
    NO_ACTIVE_SESSION as NO_ACTIVE_SESSION,
    RECORDING_DISABLED as RECORDING_DISABLED,
    SESSION_NOT_FOUND as SESSION_NOT_FOUND,
)

# Error codes surfaced by the MCP tools / CLI are defined once in
# :mod:`cerebrofy.errors` and re-exported here (via the ``recorder`` facade)
# so existing importers keep working without duplicating the literals.


class SessionNotFoundError(LookupError):
    """Raised when a session id does not exist."""

    code: str = SESSION_NOT_FOUND

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(
            f"[{SESSION_NOT_FOUND}] no session with id '{session_id}'"
        )


@dataclass(frozen=True)
class SessionEvent:
    """A single recorded MCP tool call."""

    session_id: str
    ts: int
    tool: str
    args: dict[str, Any]
    result_summary: str | None


@dataclass(frozen=True)
class SessionRecord:
    """A recorded agent session."""

    id: str
    task: str
    agent: str | None
    started_at: int
    ended_at: int | None
    outcome: str
    outcome_notes: str | None
    neurons_touched: tuple[str, ...]
    blast_radius_before: int | None
    blast_radius_after: int | None
    event_count: int

    @property
    def duration_seconds(self) -> int:
        """Wall-clock duration; 0 for sessions that are still open."""
        if self.ended_at is None:
            return 0
        return max(0, int(self.ended_at - self.started_at))

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def blast_radius_delta(self) -> int | None:
        """after − before, or None when either metric is unknown."""
        if self.blast_radius_before is None or self.blast_radius_after is None:
            return None
        return self.blast_radius_after - self.blast_radius_before


@dataclass(frozen=True)
class SessionSearchHit:
    """One `cerebrofy session search` result."""

    session: SessionRecord
    score: float
    match_kind: str  # "semantic" | "task_text"
