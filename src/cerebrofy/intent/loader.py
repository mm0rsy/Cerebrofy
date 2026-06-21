"""IntentConfig dataclass and intent.yaml I/O helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_INTENT_FILENAME = "intent.yaml"
_MAX_FILE_SIZE = 50 * 1024  # 50KB


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SprintContext:
    name: str
    goal: str
    deadline: str
    priority_lobes: tuple[str, ...]
    deprioritized_lobes: tuple[str, ...]


@dataclass(frozen=True)
class Incident:
    id: str
    date: str
    severity: str
    description: str
    affected_lobes: tuple[str, ...]
    status: str
    lesson: str


@dataclass(frozen=True)
class ArchDirection:
    direction: str
    avoid_patterns: tuple[str, ...]
    principles: tuple[str, ...]


@dataclass(frozen=True)
class TeamContext:
    concerns: tuple[str, ...]
    upcoming_risks: tuple[str, ...]


@dataclass(frozen=True)
class IntentConfig:
    sprint: SprintContext | None
    incidents: tuple[Incident, ...]
    architecture: ArchDirection | None
    team_context: TeamContext | None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.sprint:
            d["sprint"] = {
                "name": self.sprint.name,
                "goal": self.sprint.goal,
                "deadline": self.sprint.deadline,
                "priority_lobes": list(self.sprint.priority_lobes),
                "deprioritized_lobes": list(self.sprint.deprioritized_lobes),
            }
        if self.incidents:
            d["incidents"] = [
                {
                    "id": inc.id,
                    "date": inc.date,
                    "severity": inc.severity,
                    "description": inc.description,
                    "affected_lobes": list(inc.affected_lobes),
                    "status": inc.status,
                    "lesson": inc.lesson,
                }
                for inc in self.incidents
            ]
        if self.architecture:
            d["architecture"] = {
                "direction": self.architecture.direction,
                "avoid_patterns": list(self.architecture.avoid_patterns),
                "principles": list(self.architecture.principles),
            }
        if self.team_context:
            d["team_context"] = {
                "concerns": list(self.team_context.concerns),
                "upcoming_risks": list(self.team_context.upcoming_risks),
            }
        return d


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_intent(config_dir: Path) -> IntentConfig | None:
    """Load .cerebrofy/intent.yaml. Returns None if the file does not exist."""
    path = config_dir / _INTENT_FILENAME
    if not path.exists():
        return None

    size = path.stat().st_size
    if size > _MAX_FILE_SIZE:
        import sys
        print(
            f"Warning: intent.yaml exceeds 50KB ({size} bytes) — loading anyway, but consider trimming.",
            file=sys.stderr,
        )

    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    sprint = _parse_sprint(data.get("sprint"))
    incidents = tuple(_parse_incident(i) for i in data.get("incidents", []))
    architecture = _parse_architecture(data.get("architecture"))
    team_context = _parse_team_context(data.get("team_context"))

    return IntentConfig(
        sprint=sprint,
        incidents=incidents,
        architecture=architecture,
        team_context=team_context,
    )


def validate_intent(intent: IntentConfig, known_lobes: set[str]) -> list[str]:
    """Validate intent against known lobe names. Returns list of warning strings."""
    warnings: list[str] = []

    if intent.sprint:
        for lobe in intent.sprint.priority_lobes:
            if lobe not in known_lobes:
                warnings.append(f"sprint.priority_lobes: '{lobe}' not found in graph lobes")
        for lobe in intent.sprint.deprioritized_lobes:
            if lobe not in known_lobes:
                warnings.append(f"sprint.deprioritized_lobes: '{lobe}' not found in graph lobes")

    for inc in intent.incidents:
        for lobe in inc.affected_lobes:
            if lobe not in known_lobes:
                warnings.append(f"incidents[{inc.id}].affected_lobes: '{lobe}' not found in graph lobes")

    return warnings


def scaffold_intent_yaml(path: Path) -> None:
    """Write an example intent.yaml scaffold to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = """\
# .cerebrofy/intent.yaml — team context for AI agents
# Update this file at the start of each sprint.
# Commit this file — it is shared across the team.

sprint:
  name: "Sprint N"
  goal: "Describe the sprint goal here"
  deadline: "YYYY-MM-DD"
  priority_lobes: []       # Lobe names the team is focused on this sprint
  deprioritized_lobes: []  # Lobe names to deprioritize

incidents: []
# Example incident:
# - id: "INC-YYYY-NNNN"
#   date: "YYYY-MM-DD"
#   severity: critical   # critical | high | medium | low
#   description: "What went wrong"
#   affected_lobes: [lobe_name]
#   status: open         # open | patched | closed
#   lesson: "What to learn / what to always do"

architecture:
  direction: "Describe the architectural direction"
  avoid_patterns: []
  principles: []

team_context:
  concerns: []
  upcoming_risks: []
"""
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Private parsers
# ---------------------------------------------------------------------------

def _parse_sprint(data: Any) -> SprintContext | None:
    if not isinstance(data, dict):
        return None
    return SprintContext(
        name=str(data.get("name", "")),
        goal=str(data.get("goal", "")),
        deadline=str(data.get("deadline", "")),
        priority_lobes=tuple(data.get("priority_lobes") or []),
        deprioritized_lobes=tuple(data.get("deprioritized_lobes") or []),
    )


def _parse_incident(data: Any) -> Incident:
    if not isinstance(data, dict):
        return Incident(id="", date="", severity="", description="", affected_lobes=(), status="", lesson="")
    return Incident(
        id=str(data.get("id", "")),
        date=str(data.get("date", "")),
        severity=str(data.get("severity", "")),
        description=str(data.get("description", "")),
        affected_lobes=tuple(data.get("affected_lobes") or []),
        status=str(data.get("status", "")),
        lesson=str(data.get("lesson", "")),
    )


def _parse_architecture(data: Any) -> ArchDirection | None:
    if not isinstance(data, dict):
        return None
    return ArchDirection(
        direction=str(data.get("direction", "")),
        avoid_patterns=tuple(data.get("avoid_patterns") or []),
        principles=tuple(data.get("principles") or []),
    )


def _parse_team_context(data: Any) -> TeamContext | None:
    if not isinstance(data, dict):
        return None
    return TeamContext(
        concerns=tuple(data.get("concerns") or []),
        upcoming_risks=tuple(data.get("upcoming_risks") or []),
    )
