"""Intent enrichment — cross-reference lobes/neurons against intent.yaml context."""

from __future__ import annotations

import json
from typing import Any

from cerebrofy.intent.loader import IntentConfig


def enrich_with_intent(
    affected_lobes: list[str],
    intent: IntentConfig,
) -> dict[str, Any]:
    """Compute intent_context for a set of affected lobes.

    Returns a dict suitable for embedding in any MCP tool response.
    """
    result: dict[str, Any] = {}

    if intent.sprint:
        priority = set(intent.sprint.priority_lobes)
        deprioritized = set(intent.sprint.deprioritized_lobes)
        overlap = [lobe for lobe in affected_lobes if lobe in priority]
        depr_overlap = [lobe for lobe in affected_lobes if lobe in deprioritized]

        if overlap:
            relevance = f"HIGH — {', '.join(overlap)} is a priority lobe this sprint"
        elif depr_overlap:
            relevance = f"LOW — {', '.join(depr_overlap)} is deprioritized this sprint"
        elif affected_lobes:
            relevance = "MEDIUM — lobe not explicitly prioritized or deprioritized"
        else:
            relevance = "UNKNOWN — no lobe context provided"

        result["sprint_relevance"] = relevance
        result["sprint"] = {
            "name": intent.sprint.name,
            "goal": intent.sprint.goal,
            "deadline": intent.sprint.deadline,
        }

    active_incidents = [
        f"{inc.id} — {inc.description} (severity: {inc.severity}, status: {inc.status})"
        for inc in intent.incidents
        if any(lobe in inc.affected_lobes for lobe in affected_lobes)
        and inc.status not in ("closed", "patched")
    ]
    if active_incidents:
        result["active_incidents"] = active_incidents

    if intent.architecture:
        guidance_parts: list[str] = []
        for pattern in intent.architecture.avoid_patterns:
            guidance_parts.append(f"AVOID: {pattern}")
        for principle in intent.architecture.principles:
            guidance_parts.append(f"PRINCIPLE: {principle}")
        if guidance_parts:
            result["architectural_guidance"] = guidance_parts

    if intent.team_context:
        matching_concerns = [
            c for c in intent.team_context.concerns
            if any(lobe in c for lobe in affected_lobes)
        ]
        if matching_concerns:
            result["priority"] = matching_concerns[0]
        if intent.team_context.upcoming_risks:
            result["upcoming_risks"] = list(intent.team_context.upcoming_risks)

    return result


def summary_intent(intent: IntentConfig) -> dict[str, Any]:
    """Return a compact summary of intent for cross-cutting injection (no lobe context)."""
    summary: dict[str, Any] = {}

    if intent.sprint:
        summary["sprint"] = intent.sprint.name
        summary["sprint_goal"] = intent.sprint.goal
        if intent.sprint.deadline:
            summary["sprint_deadline"] = intent.sprint.deadline
        if intent.sprint.priority_lobes:
            summary["priority_lobes"] = list(intent.sprint.priority_lobes)

    open_incidents = [inc for inc in intent.incidents if inc.status not in ("closed", "patched")]
    if open_incidents:
        summary["open_incidents"] = len(open_incidents)
        summary["incident_ids"] = [inc.id for inc in open_incidents]

    return summary


def inject_intent(response_text: str, intent: IntentConfig) -> str:
    """Inject a compact intent summary into a JSON response string.

    Non-JSON responses are returned unchanged (intent context is only useful in structured output).
    """
    try:
        data = json.loads(response_text)
        if isinstance(data, dict):
            data["intent_context"] = summary_intent(intent)
            return json.dumps(data, indent=2)
    except (json.JSONDecodeError, ValueError):
        pass
    return response_text
