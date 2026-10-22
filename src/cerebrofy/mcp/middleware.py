"""Cerebrofy MCP middleware hook for coordination conflict checks.

As specified in IDEA.md § "MCP Middleware Hook":
Every MCP tool handler that operates on a neuron calls `check_conflicts()`
and prepends any conflict notices to the response. This is additive —
existing responses are enriched, not replaced.

This module integrates with the ActiveAgentRegistry and ConflictDetector
to provide:
1. Claim conflict detection (is neuron claimed by another agent?)
2. Memory contradiction detection (two memories with opposite bodies on same neuron)
3. Lobe-awareness (other agents working in same lobe)

The middleware wraps tool handlers following the existing pattern from
_handle_search_code, _handle_remember, etc.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent

from cerebrofy.coordination.registry import ActiveAgentRegistry
from cerebrofy.coordination.conflict_detector import ConflictDetector, MemoryContradictionDetector


def _resolve_root() -> Any:
    """Shared repo-root resolution — reuse the existing helper from server.py."""
    from cerebrofy.utils.paths import require_repo_root
    return require_repo_root(Path.cwd())


# ---------------------------------------------------------------------------
# Public API: called by each MCP tool handler wrapping real code
# ---------------------------------------------------------------------------

def check_conflicts(
    neuron_id: str,
    requesting_agent: str,
    memories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run all conflict checks for a neuron and return additive notices.

    Returns dict with keys:
    - claim_conflicts: list of agents already claiming this neuron
    - memory_conflicts: list of dicts describing contradicting memories
    - lobe_awareness: list of agents in the same lobe
    - has_claim_conflict: bool
    - has_memory_conflict: bool
    - has_lobe_activity: bool
    """
    from cerebrofy.db.connection import open_db
    from cerebrofy.db.schema import create_session_schema, create_memory_schema

    # Ensure DB schema is seeded (idempotent; active_agents table created on
    # registry init; this just guarantees memories/sessions are available)
    db = open_db(_resolve_root() / ".cerebrofy" / "db" / "cerebrofy.db")
    create_session_schema(db)
    create_memory_schema(db)

    registry = ActiveAgentRegistry(str(_resolve_root() / ".cerebrofy" / "db" / "cerebrofy.db"))
    detector = ConflictDetector(registry=registry)
    mem_detector = MemoryContradictionDetector()

    # 1. Claim collision
    claim_check = detector.detect_claim_conflicts(neuron_id, requesting_agent)
    claim_conflicts = claim_check["claim_conflicts"]
    has_claim_conflict = claim_check["has_conflict"]

    # 2. Memory contradiction
    memory_conflicts = []
    has_memory_conflict = False
    if memories is not None:
        mem_contradictions = mem_detector.detect_memory_contradictions(neuron_id, memories)
        memory_conflicts = mem_contradictions
        has_memory_conflict = len(mem_contradictions) > 0

    # 3. Lobe awareness (other agents claiming neurons in the same lobe)
    # Extract lobe from neuron ID format: lobe/file::neuron or file::neuron
    lobe = neuron_id.split("/")[0] if "/" in neuron_id else ""
    lobe_awareness = []
    active_agents = registry.get_active_agents()
    for agent_id, agent_data in active_agents.items():
        if agent_id == requesting_agent:
            continue
        for claimed_neuron in agent_data["claimed_neurons"]:
            claimed_lobe = claimed_neuron.split("/")[0] if "/" in claimed_neuron else ""
            if claimed_lobe == lobe:
                lobe_awareness.append({
                    "agent_id": agent_id,
                    "agent_type": agent_data["agent_type"],
                    "intent": agent_data["intent"],
                    "active_minutes": (
                        (int(__import__("time").time()) - agent_data["started_ts"]) // 60
                        if agent_data.get("started_ts")
                        else 0
                    ),
                })
                break  # one claim per agent is enough

    has_lobe_activity = len(lobe_awareness) > 0

    return {
        "neuron": neuron_id,
        "claim_conflicts": claim_conflicts,
        "has_claim_conflict": has_claim_conflict,
        "memory_conflicts": memory_conflicts,
        "has_memory_conflict": has_memory_conflict,
        "lobe_awareness": lobe_awareness,
        "has_lobe_activity": has_lobe_activity,
    }


def enrich_response(
    response: list[TextContent],
    neuron_id: str,
    requesting_agent: str,
    memories: list[dict[str, Any]] | None = None,
) -> list[TextContent]:
    """Prepend conflict notices to an MCP tool response (additive, not replacing)."""

    notices = check_conflicts(neuron_id, requesting_agent, memories=memories)

    if not any(
        [
            notices["has_claim_conflict"],
            notices["has_memory_conflict"],
            notices["has_lobe_activity"],
        ]
    ):
        # No conflicts — return original response unchanged
        return response

    # Build additive notice payload
    notice_parts = []

    if notices["has_claim_conflict"]:
        claimants = [
            f"{c['agent_id']} ({c['intent']})"
            for c in notices["claim_conflicts"]
        ]
        notice_parts.append(
            f"⚠️ Claim conflict: {', '.join(claimants)} already claim(s) on {notices['neuron']}."
        )

    if notices["has_memory_conflict"]:
        for mc in notices["memory_conflicts"]:
            notice_parts.append(
                f"💭 Memory contradiction on {mc['neuron']}: "
                f"[{mc['memory_a']['id']}] vs [{mc['memory_b']['id']}]"
            )

    if notices["has_lobe_activity"]:
        lobe_agents = [a["agent_id"] for a in notices["lobe_awareness"]]
        notice_parts.append(
            f"ℹ️ Other agents active in lobe '{neuron_id.split('/')[0]}': "
            f"{', '.join(lobe_agents)}."
        )

    # Prepend as a TextContent at the beginning
    notice_text = "\n".join(notice_parts)
    notice_content = TextContent(type="text", text=notice_text)

    # Return notice first, then original responses
    return [notice_content] + response


# ---------------------------------------------------------------------------
# Example wrapper pattern — how each tool handler should integrate
# ---------------------------------------------------------------------------

def wrap_with_conflict_check(
    handler_func,
    neuron_id_arg_key: str = "neuron",
    memories_arg_key: str | None = None,
):
    """Decorator-like wrapper for MCP tool handlers.

    Usage (inside a handler):
        arguments = {..., "neuron": "...", ...}
        enriched = wrap_with_conflict_check(_handle_search_code)(arguments)
        return enriched

    The wrapper:
    1. Extracts neuron_id from arguments
    2. Extracts memories from arguments if memories_arg_key given
    3. Calls check_conflicts
    4. Calls original handler
    5. Enriches the handler's response with additive conflict notices
    """

    def wrapper(arguments: dict[str, Any]) -> list[Any]:
        neuron_id = arguments.get(neuron_id_arg_key)
        if not neuron_id:
            # Let the original handler validate
            return handler_func(arguments)

        # Extract memories if the handler stores them under a known key
        memories = None
        if memories_arg_key and memories_arg_key in arguments:
            memories = arguments[memories_arg_key]

        # Run original handler
        result = handler_func(arguments)

        # Enrich the result
        requesting_agent = arguments.get("agent_id", "claude")
        enriched = enrich_response(result, neuron_id, requesting_agent, memories=memories)
        return enriched

    return wrapper