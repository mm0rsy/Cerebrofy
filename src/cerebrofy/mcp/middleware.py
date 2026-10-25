"""Cerebrofy MCP middleware hook for coordination conflict checks.

As specified in IDEA.md § "MCP Middleware Hook": MCP tool handlers that
operate on a neuron call :func:`check_conflicts` and prepend any conflict
notices to the response. This is additive — existing responses are enriched,
never replaced.

This module integrates with the :class:`ActiveAgentRegistry` and
:class:`ConflictDetector` to provide:

1. claim conflict detection (is the neuron claimed by another agent?);
2. memory contradiction detection (two memories with opposite bodies on the
   same neuron);
3. lobe awareness (other agents working in the same lobe).

Every helper here is best-effort: a missing index, an empty registry or an
unavailable coordination core yields "no conflicts" rather than an exception.
Connections are always closed, and no DDL is performed here (the registry owns
its schema).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.types import TextContent

from cerebrofy.coordination.conflict_detector import ConflictDetector
from cerebrofy.coordination.registry import ActiveAgentRegistry


def _empty_conflicts(neuron_id: str) -> dict[str, Any]:
    """Return the no-conflict result shape used by every failure path."""
    return {
        "neuron": neuron_id,
        "claim_conflicts": [],
        "has_claim_conflict": False,
        "memory_conflicts": [],
        "has_memory_conflict": False,
        "lobe_awareness": [],
        "has_lobe_activity": False,
    }


def _resolve_root() -> Path | None:
    """Resolve the project root, or ``None`` when there is no Cerebrofy repo."""
    from cerebrofy.utils.paths import find_repo_root

    try:
        return find_repo_root(Path.cwd())
    except Exception as exc:  # noqa: BLE001
        return None


def _open_registry(root: Path) -> ActiveAgentRegistry | None:
    """Open a read-only registry handle, or ``None`` if the DB is unavailable.

    Middleware must never mutate coordination state: the registry is opened
    ``readonly=True`` so it cannot create/upgrade schema or run cleanup, and
    every query passes ``cleanup=False``. Any failure degrades to "no
    conflicts".
    """
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return None
    try:
        return ActiveAgentRegistry(str(db_path), readonly=True)
    except Exception as exc:  # noqa: BLE001
        return None


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _lobe_of(neuron_id: str) -> str:
    return neuron_id.split("/")[0] if "/" in neuron_id else ""


def _claim_conflicts_from_agents(
    agents: dict[str, dict[str, Any]], neuron_id: str, requesting_agent: str
) -> list[dict[str, Any]]:
    """Return other agents claiming *neuron_id* from an agent snapshot."""
    conflicts: list[dict[str, Any]] = []
    for agent_id, agent_data in agents.items():
        if agent_id == requesting_agent or not isinstance(agent_data, dict):
            continue
        claimed = agent_data.get("claimed_neurons") or []
        if isinstance(claimed, list) and neuron_id in claimed:
            conflicts.append(
                {
                    "agent_id": agent_id,
                    "agent_type": agent_data.get("agent_type"),
                    "intent": agent_data.get("intent") or "",
                    "active_minutes": agent_data.get("active_minutes", 0),
                }
            )
    return conflicts


def _lobe_awareness_from_agents(
    agents: dict[str, dict[str, Any]], neuron_id: str, requesting_agent: str
) -> list[dict[str, Any]]:
    """Return other agents working in the same lobe as *neuron_id*."""
    lobe = _lobe_of(neuron_id)
    if not lobe:
        return []

    awareness: list[dict[str, Any]] = []
    for agent_id, agent_data in agents.items():
        if agent_id == requesting_agent or not isinstance(agent_data, dict):
            continue
        claimed = agent_data.get("claimed_neurons") or []
        if not isinstance(claimed, list):
            continue
        for claimed_neuron in claimed:
            if not isinstance(claimed_neuron, str):
                continue
            if _lobe_of(claimed_neuron) == lobe:
                awareness.append(
                    {
                        "agent_id": agent_id,
                        "agent_type": agent_data.get("agent_type"),
                        "intent": agent_data.get("intent") or "",
                        "active_minutes": agent_data.get("active_minutes", 0),
                    }
                )
                break
    return awareness


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_conflicts(
    neuron_id: str,
    requesting_agent: str,
    memories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run all conflict checks for a neuron and return additive notices.

    Returns a dict with keys ``claim_conflicts``, ``has_claim_conflict``,
    ``memory_conflicts``, ``has_memory_conflict``, ``lobe_awareness`` and
    ``has_lobe_activity``. Never raises: any infrastructure failure is treated
    as "no conflicts".
    """
    result = _empty_conflicts(neuron_id)

    root = _resolve_root()
    if root is None:
        return result

    registry = _open_registry(root)
    if registry is None:
        return result

    try:
        # Single read-only snapshot, no stale-claim cleanup and no DDL. This
        # keeps the middleware responsive even while another process holds
        # ``BEGIN IMMEDIATE`` (reads still succeed; writes would block).
        try:
            agents = registry.get_active_agents(cleanup=False)
        except Exception as exc:  # noqa: BLE001
            agents = {}

        if isinstance(agents, dict) and agents:
            try:
                claim_conflicts = _claim_conflicts_from_agents(
                    agents, neuron_id, requesting_agent
                )
                result["claim_conflicts"] = claim_conflicts
                result["has_claim_conflict"] = bool(claim_conflicts)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")
            try:
                lobe_awareness = _lobe_awareness_from_agents(
                    agents, neuron_id, requesting_agent
                )
                result["lobe_awareness"] = lobe_awareness
                result["has_lobe_activity"] = bool(lobe_awareness)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")
        if memories:
            try:
                detector = ConflictDetector(
                    memories_db_path=registry.db_path.parent / "memories.db"
                )
                memory_conflicts = detector.detect_memory_contradictions(
                    neuron_id, memories
                )
                result["memory_conflicts"] = _as_dict_list(memory_conflicts)
                result["has_memory_conflict"] = bool(result["memory_conflicts"])
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")
    finally:
        try:
            registry.close()
        except Exception as exc:  # pragma: no cover - close is best-effort  # noqa: BLE001
            pass

    return result


def _claimant_label(conflict: dict[str, Any]) -> str:
    agent = (
        conflict.get("agent_id")
        or conflict.get("existing_claimant")
        or conflict.get("agent")
        or "unknown"
    )
    intent = conflict.get("intent") or conflict.get("claimant_intent") or ""
    return f"{agent} ({intent})" if intent else str(agent)


def enrich_response(
    response: list[TextContent],
    neuron_id: str,
    requesting_agent: str,
    memories: list[dict[str, Any]] | None = None,
) -> list[TextContent]:
    """Prepend conflict notices to an MCP tool response (additive, not replacing)."""
    notices = check_conflicts(neuron_id, requesting_agent, memories=memories)

    if not any(
        (
            notices["has_claim_conflict"],
            notices["has_memory_conflict"],
            notices["has_lobe_activity"],
        )
    ):
        # No conflicts — return the original response object unchanged.
        return response

    notice_parts: list[str] = []

    if notices["has_claim_conflict"]:
        claimants = ", ".join(
            _claimant_label(conflict) for conflict in notices["claim_conflicts"]
        )
        notice_parts.append(
            f"⚠️ Claim conflict: {claimants} already claim(s) {notices['neuron']}."
        )

    if notices["has_memory_conflict"]:
        for conflict in notices["memory_conflicts"]:
            memory_a = conflict.get("memory_a") or {}
            memory_b = conflict.get("memory_b") or {}
            id_a = memory_a.get("id") if isinstance(memory_a, dict) else None
            id_b = memory_b.get("id") if isinstance(memory_b, dict) else None
            notice_parts.append(
                f"💭 Memory contradiction on {conflict.get('neuron') or neuron_id}: "
                f"[{id_a}] vs [{id_b}]"
            )

    if notices["has_lobe_activity"]:
        lobe = _lobe_of(neuron_id)
        lobe_agents = ", ".join(
            str(agent.get("agent_id", "unknown")) for agent in notices["lobe_awareness"]
        )
        notice_parts.append(
            f"ℹ️ Other agents active in lobe '{lobe}': {lobe_agents}."
        )

    notice_content = TextContent(type="text", text="\n".join(notice_parts))
    return [notice_content] + response


__all__ = ["check_conflicts", "enrich_response"]
