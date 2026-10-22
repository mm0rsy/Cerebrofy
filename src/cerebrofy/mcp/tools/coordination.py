"""MCP handlers for multi-agent coordination (Idea #25).

Tools: ``cerebrofy_claim``, ``cerebrofy_release``, ``cerebrofy_who``,
``cerebrofy_conflicts`` and ``cerebrofy_resolve``.

Coordination state lives in the local index database
(``<root>/.cerebrofy/db/cerebrofy.db``), so claims are visible to every
Cerebrofy process on this machine. Nothing is uploaded.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from cerebrofy.coordination.constants import MAX_TTL_MINUTES, RESOLUTION_OPTIONS
from cerebrofy.errors import (
    CEREBROFY_ERROR,
    CONFIG_ERROR,
    NEURON_ALREADY_CLAIMED,
    NO_INDEX,
    CerebrofyError,
)
from cerebrofy.mcp.errors import mcp_error as _err
from cerebrofy.utils.paths import find_repo_root as _find_repo_root_impl

_STRATEGY_ALIASES: dict[str, str] = {
    "newest": "keep_newest",
    "keep_newest": "keep_newest",
    "author": "keep_by_author",
    "keep_by_author": "keep_by_author",
    "review": "human_review",
    "human_review": "human_review",
    "merge": "merge",
}


def _find_root(cwd: Path) -> Path:
    """Resolve the repo root from *cwd* (delegates to the shared helper).

    Honors an explicit ``--root``/``CEREBROFY_ROOT`` binding before walking up
    so a manipulated CWD cannot redirect the tool at another project.
    """
    root = _find_repo_root_impl(cwd)
    if root is None:
        raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")
    return root


def _db_path(root: Path) -> Path:
    return root / ".cerebrofy" / "db" / "cerebrofy.db"


def _open_registry(root: Path, *, readonly: bool = False) -> Any:
    """Open the active-agent registry against the local index database.

    Refuses to create the index: coordination tools operate on an existing
    project and must never silently materialise ``cerebrofy.db``. Read-only
    handles are used by ``cerebrofy_who`` / ``cerebrofy_conflicts`` so those
    tools never run schema DDL or stale-claim cleanup.
    """
    db_path = _db_path(root)
    if not db_path.exists():
        raise FileNotFoundError("Index not found. Run 'cerebrofy build' first.")

    from cerebrofy.coordination.registry import ActiveAgentRegistry

    return ActiveAgentRegistry(str(db_path), readonly=readonly)


def _close_registry(registry: Any) -> None:
    if registry is None:
        return
    try:
        registry.close()
    except Exception:  # pragma: no cover - close is best-effort
        pass


def _error_text(code: str, message: str) -> list[Any]:
    return _err(f"[{code}] {message}")


def _resolve_root_or_error() -> tuple[Path | None, list[Any] | None]:
    try:
        return _find_root(Path.cwd()), None
    except Exception:
        return None, _error_text(
            NO_INDEX, "could not find .cerebrofy directory. Run 'cerebrofy init' first."
        )


def _require_agent_id(arguments: dict[str, Any]) -> str | None:
    raw = arguments.get("agent_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _parse_neuron_list(
    raw: Any, *, required: bool
) -> tuple[list[str] | None, str | None]:
    """Validate a ``neurons`` argument.

    Returns ``(neurons, None)`` on success, ``(None, message)`` on failure and
    ``(None, None)`` when the argument is absent and not required.
    """
    if raw is None:
        if required:
            return None, "'neurons' is required — pass a non-empty list of neuron ids."
        return None, None
    if not isinstance(raw, list):
        return None, "'neurons' must be a list of neuron id strings."
    if not raw:
        if required:
            return None, "'neurons' must contain at least one neuron id."
        return None, None
    neurons: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            return None, "every entry in 'neurons' must be a non-empty string."
        neurons.append(item.strip())
    return neurons, None


# ---------------------------------------------------------------------------
# cerebrofy_claim
# ---------------------------------------------------------------------------

def handle_claim(arguments: dict[str, Any]) -> list[Any]:
    """Claim one or more neurons for an agent before editing them."""
    from mcp.types import TextContent

    agent_id = _require_agent_id(arguments)
    if agent_id is None:
        return _error_text("error", "'agent_id' is required and must be a non-empty string.")

    neurons, neuron_error = _parse_neuron_list(arguments.get("neurons"), required=True)
    if neuron_error is not None:
        return _err(f"[error] {neuron_error}")
    assert neurons is not None

    intent = str(arguments.get("intent") or "").strip()
    if not intent:
        return _err("[error] 'intent' is required — describe what you are about to do.")

    agent_type = str(arguments.get("agent_type") or "claude").strip() or "claude"
    raw_ttl = arguments.get("ttl_minutes", 60)
    try:
        ttl_minutes = int(raw_ttl)
    except (TypeError, ValueError):
        return _err(f"[error] 'ttl_minutes' must be an integer, got {raw_ttl!r}.")
    ttl_minutes = max(1, min(ttl_minutes, MAX_TTL_MINUTES))

    session_id = arguments.get("session_id")
    session_id_str = str(session_id).strip() if session_id else None

    root, root_error = _resolve_root_or_error()
    if root is None:
        assert root_error is not None
        return root_error

    # Accept file paths as well as literal ``file::name`` neuron ids, exactly
    # like the CLI surface does.
    from cerebrofy.coordination.neurons import expand_neurons

    neurons = expand_neurons(root, neurons)

    registry: Any = None
    try:
        registry = _open_registry(root)
        result = registry.claim_neurons(
            agent_id,
            neurons,
            intent,
            agent_type=agent_type,
            ttl_minutes=ttl_minutes,
            session_id=session_id_str,
        )
    except FileNotFoundError as exc:
        return _error_text(NO_INDEX, str(exc))
    except CerebrofyError as exc:
        return _error_text(exc.code, str(exc))
    except Exception as exc:
        return _error_text(CEREBROFY_ERROR, f"cerebrofy_claim failed: {exc}")
    finally:
        _close_registry(registry)

    if not isinstance(result, dict):
        return _error_text(CEREBROFY_ERROR, "cerebrofy_claim returned an unexpected payload.")

    if result.get("error") == NEURON_ALREADY_CLAIMED:
        message = str(
            result.get("message")
            or "one or more neurons are already claimed by another active agent."
        )
        # Keep the conflict details (existing claimant, intent, age) alongside
        # the stable code so callers can act on the collision.
        return _err(
            json.dumps(
                {
                    "error": NEURON_ALREADY_CLAIMED,
                    "message": message,
                    "conflicts": result.get("conflicts", []),
                },
                indent=2,
            )
        )

    payload = {
        "claimed": result.get("claimed", []),
        "conflicts": result.get("conflicts", []),
        "claim_id": result.get("claim_id"),
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


# ---------------------------------------------------------------------------
# cerebrofy_release
# ---------------------------------------------------------------------------

def handle_release(arguments: dict[str, Any]) -> list[Any]:
    """Release specific neurons (or every claim) held by an agent."""
    from mcp.types import TextContent

    agent_id = _require_agent_id(arguments)
    if agent_id is None:
        return _error_text("error", "'agent_id' is required and must be a non-empty string.")

    neurons, neuron_error = _parse_neuron_list(arguments.get("neurons"), required=False)
    if neuron_error is not None:
        return _err(f"[error] {neuron_error}")

    root, root_error = _resolve_root_or_error()
    if root is None:
        assert root_error is not None
        return root_error

    release_all = not neurons
    if neurons:
        from cerebrofy.coordination.neurons import expand_neurons

        neurons = expand_neurons(root, neurons)

    registry: Any = None
    try:
        registry = _open_registry(root)
        if neurons:
            result = registry.release_neurons(agent_id, neurons)
        else:
            result = registry.release_all(agent_id)
    except FileNotFoundError as exc:
        return _error_text(NO_INDEX, str(exc))
    except CerebrofyError as exc:
        return _error_text(exc.code, str(exc))
    except Exception as exc:
        return _error_text(CEREBROFY_ERROR, f"cerebrofy_release failed: {exc}")
    finally:
        _close_registry(registry)

    if not isinstance(result, dict):
        return _error_text(CEREBROFY_ERROR, "cerebrofy_release returned an unexpected payload.")

    released = result.get("released", [])
    payload = {
        "agent_id": agent_id,
        "released": released,
        "released_count": len(released) if isinstance(released, list) else 0,
        "released_all": release_all,
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


# ---------------------------------------------------------------------------
# cerebrofy_who
# ---------------------------------------------------------------------------

def _active_minutes(agent_data: dict[str, Any], now: int) -> int:
    started = agent_data.get("started_ts")
    if not isinstance(started, (int, float)):
        return 0
    return max(0, (now - int(started)) // 60)


def handle_who(arguments: dict[str, Any]) -> list[Any]:
    """List every active agent, their claims, and overlapping-claim conflicts."""
    from mcp.types import TextContent

    root, root_error = _resolve_root_or_error()
    if root is None:
        assert root_error is not None
        return root_error

    registry: Any = None
    try:
        registry = _open_registry(root, readonly=True)
        agents = registry.get_active_agents(cleanup=False)
        try:
            conflicts = registry.detect_overlapping_claims()
        except Exception:
            conflicts = []
    except FileNotFoundError as exc:
        return _error_text(NO_INDEX, str(exc))
    except Exception as exc:
        return _error_text(CEREBROFY_ERROR, f"cerebrofy_who failed: {exc}")
    finally:
        _close_registry(registry)

    now = int(time.time())
    rows: list[dict[str, Any]] = []
    for agent_id, data in (agents or {}).items():
        rows.append(
            {
                "agent_id": agent_id,
                "agent_type": data.get("agent_type"),
                "intent": data.get("intent") or "",
                "claimed_neurons": list(data.get("claimed_neurons") or []),
                "active_minutes": _active_minutes(data, now),
                "session_id": data.get("session_id"),
            }
        )

    payload = {
        "active_agents": rows,
        "conflicts": conflicts or [],
        "total_active": len(rows),
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


# ---------------------------------------------------------------------------
# cerebrofy_conflicts
# ---------------------------------------------------------------------------

def handle_conflicts(arguments: dict[str, Any]) -> list[Any]:
    """Report overlapping claims and contradicting memories."""
    from mcp.types import TextContent

    neuron = arguments.get("neuron")
    neuron_str = str(neuron).strip() if neuron else None

    root, root_error = _resolve_root_or_error()
    if root is None:
        assert root_error is not None
        return root_error

    registry: Any = None
    try:
        registry = _open_registry(root, readonly=True)
        overlapping = registry.detect_overlapping_claims()
        memory_conflicts = registry.detect_memory_conflicts(neuron_str)
    except FileNotFoundError as exc:
        return _error_text(NO_INDEX, str(exc))
    except Exception as exc:
        return _error_text(CEREBROFY_ERROR, f"cerebrofy_conflicts failed: {exc}")
    finally:
        _close_registry(registry)

    payload = {
        "overlapping_claims": overlapping or [],
        "memory_conflicts": memory_conflicts or [],
        "resolution_options": list(RESOLUTION_OPTIONS),
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


# ---------------------------------------------------------------------------
# cerebrofy_resolve
# ---------------------------------------------------------------------------

def handle_resolve(arguments: dict[str, Any]) -> list[Any]:
    """Resolve a pair of contradicting memories with a deterministic strategy."""
    from mcp.types import TextContent

    memory_a = str(arguments.get("memory_a") or "").strip()
    memory_b = str(arguments.get("memory_b") or "").strip()
    if not memory_a or not memory_b:
        return _err("[error] 'memory_a' and 'memory_b' are required memory ids.")
    if memory_a == memory_b:
        return _err("[error] 'memory_a' and 'memory_b' must be different memories.")

    raw_strategy = str(arguments.get("strategy") or "").strip().lower()
    strategy = _STRATEGY_ALIASES.get(raw_strategy)
    if strategy is None:
        return _err(
            f"[error] 'strategy' must be one of: {', '.join(RESOLUTION_OPTIONS)}."
        )

    neuron = arguments.get("neuron")
    neuron_str = str(neuron).strip() if neuron else None
    author = arguments.get("author")
    author_str = str(author).strip() if author else None
    merged_body = arguments.get("merged_body")
    merged_body_str = str(merged_body) if merged_body is not None else None

    root, root_error = _resolve_root_or_error()
    if root is None:
        assert root_error is not None
        return root_error

    if not _db_path(root).exists():
        return _error_text(NO_INDEX, "Index not found. Run 'cerebrofy build' first.")

    try:
        from cerebrofy.coordination.resolver import ConflictResolver
    except Exception as exc:
        return _error_text(CEREBROFY_ERROR, f"coordination core unavailable: {exc}")

    try:
        resolver = ConflictResolver(root / ".cerebrofy")
        result = resolver.resolve_pair(
            memory_a,
            memory_b,
            strategy,
            neuron=neuron_str,
            author=author_str,
            merged_body=merged_body_str,
        )
    except FileNotFoundError as exc:
        return _error_text(NO_INDEX, str(exc))
    except ValueError as exc:
        # Invalid arguments (unknown memory id, missing author/merged_body,
        # etc.) are configuration errors, not coordination failures.
        return _error_text(CONFIG_ERROR, str(exc))
    except CerebrofyError as exc:
        return _error_text(exc.code, str(exc))
    except Exception as exc:
        return _error_text(CEREBROFY_ERROR, f"cerebrofy_resolve failed: {exc}")

    if not isinstance(result, dict):
        return _error_text(CEREBROFY_ERROR, "cerebrofy_resolve returned an unexpected payload.")

    payload = dict(result)
    payload.setdefault("strategy", strategy)
    if strategy == "human_review":
        # Human review is advisory: never mutate memory state on the agent's behalf.
        payload["requires_review"] = True

    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


__all__ = [
    "handle_claim",
    "handle_release",
    "handle_who",
    "handle_conflicts",
    "handle_resolve",
]
