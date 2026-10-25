"""Unit tests for the declarative MCP tool registry (Lane A1).

These tests pin the contract that the ``TOOL_SPECS`` registry in
:mod:`cerebrofy.mcp.tool_specs` and the ``_HANDLERS``/``dispatch_tool`` wiring in
:mod:`cerebrofy.mcp.server` implement:

* the 36-tool catalog, in the exact advertised order;
* the inject/no-inject split;
* every spec resolves to a real ``_handle_*`` handler;
* ``dispatch_tool`` returns the documented ``Unknown tool:`` error for unknown
  names and routes known names through ``_HANDLERS``.

The pure-catalog assertions (order, count, inject flags, schema presence) only
import :mod:`cerebrofy.mcp.tool_specs`, which is stdlib-only, so they run even
when the optional ``mcp`` extra is absent. The dispatch/handler assertions need
:class:`cerebrofy.mcp.server` (which imports ``mcp``), so they ``importorskip``
the ``mcp`` extra and skip gracefully in a no-mcp environment.
"""

from __future__ import annotations

import asyncio

import pytest

from cerebrofy.mcp.tool_specs import SPEC_BY_NAME, TOOL_SPECS, ToolSpec

EXPECTED_ORDER: list[str] = [
    "search_code",
    "get_neuron",
    "list_lobes",
    "cerebrofy_list_resources",
    "cerebrofy_context",
    "cerebrofy_blast_radius",
    "cerebrofy_epistemic",
    "cerebrofy_health",
    "cerebrofy_intent",
    "cerebrofy_build",
    "cerebrofy_update",
    "cerebrofy_validate",
    "cerebrofy_remember",
    "cerebrofy_recall",
    "cerebrofy_memories",
    "cerebrofy_link_memories",
    "cerebrofy_trace_history",
    "cerebrofy_onboard",
    "cerebrofy_impact",
    "cerebrofy_silo",
    "cerebrofy_coverage_gap",
    "cerebrofy_vuln",
    "cerebrofy_upgrade",
    "cerebrofy_arch_check",
    "cerebrofy_session_start",
    "cerebrofy_session_end",
    "cerebrofy_session_show",
    "cerebrofy_plan",
    "cerebrofy_changelog",
    "cerebrofy_governance",
    "cerebrofy_review",
    "cerebrofy_claim",
    "cerebrofy_release",
    "cerebrofy_who",
    "cerebrofy_conflicts",
    "cerebrofy_resolve",
    "cerebrofy_insights",
    "cerebrofy_synthesize",
    "cerebrofy_narrative",
]

# Data-reading tools that receive epistemic + intent enrichment at dispatch time.
INJECT_TRUE: set[str] = {
    "cerebrofy_health",
    "cerebrofy_context",
    "cerebrofy_blast_radius",
    "search_code",
    "get_neuron",
    "list_lobes",
    "cerebrofy_onboard",
    "cerebrofy_impact",
    "cerebrofy_silo",
    "cerebrofy_coverage_gap",
    "cerebrofy_vuln",
    "cerebrofy_arch_check",
    "cerebrofy_changelog",
    "cerebrofy_governance",
    "cerebrofy_review",
    "cerebrofy_who",
    "cerebrofy_conflicts",
    "cerebrofy_insights",
    "cerebrofy_synthesize",
    "cerebrofy_narrative",
}

# Self-contained / side-effecting tools: results are returned verbatim.
INJECT_FALSE: set[str] = {
    "cerebrofy_epistemic",
    "cerebrofy_intent",
    "cerebrofy_list_resources",
    "cerebrofy_build",
    "cerebrofy_update",
    "cerebrofy_validate",
    "cerebrofy_remember",
    "cerebrofy_recall",
    "cerebrofy_memories",
    "cerebrofy_link_memories",
    "cerebrofy_trace_history",
    "cerebrofy_plan",
    "cerebrofy_upgrade",
    "cerebrofy_session_start",
    "cerebrofy_session_end",
    "cerebrofy_session_show",
    "cerebrofy_claim",
    "cerebrofy_release",
    "cerebrofy_resolve",
}


# ---------------------------------------------------------------------------
# Catalog structure (no mcp dependency)
# ---------------------------------------------------------------------------


def test_tool_specs_count_is_39() -> None:
    assert len(TOOL_SPECS) == 39


def test_tool_specs_order_matches_catalog() -> None:
    assert [s.name for s in TOOL_SPECS] == EXPECTED_ORDER


def test_spec_by_name_has_39_unique_entries() -> None:
    assert len(SPEC_BY_NAME) == 39
    assert set(SPEC_BY_NAME) == set(EXPECTED_ORDER)


def test_no_duplicate_names_raised_at_build() -> None:
    """Re-constructing the lookup from TOOL_SPECS must yield exactly 39 keys
    (a duplicate would have raised ValueError at import time)."""
    rebuilt: dict[str, ToolSpec] = {}
    for s in TOOL_SPECS:
        assert s.name not in rebuilt
        rebuilt[s.name] = s
    assert len(rebuilt) == 39


@pytest.mark.parametrize("spec", TOOL_SPECS)
def test_each_spec_has_required_fields(spec: ToolSpec) -> None:
    assert spec.name
    assert spec.description.strip()
    assert spec.input_schema["type"] == "object"
    assert "properties" in spec.input_schema
    assert spec.handler_name
    # handler_name must point at a _handle_* implementation
    assert spec.handler_name.startswith("_handle_")


@pytest.mark.parametrize("spec", TOOL_SPECS)
def test_inject_flag_partition(spec: ToolSpec) -> None:
    if spec.name in INJECT_TRUE:
        assert spec.inject is True
    elif spec.name in INJECT_FALSE:
        assert spec.inject is False
    else:  # pragma: no cover - guard against drift between the two sets
        pytest.fail(f"{spec.name} not classified in INJECT_TRUE/INJECT_FALSE")


def test_inject_sets_partition_the_catalog() -> None:
    assert INJECT_TRUE | INJECT_FALSE == set(EXPECTED_ORDER)
    assert INJECT_TRUE.isdisjoint(INJECT_FALSE)
    assert len(INJECT_TRUE) == 20
    assert len(INJECT_FALSE) == 19


def test_coordination_read_tools_are_inject_true() -> None:
    """``who``/``conflicts`` read data, so they get epistemic/intent enrichment."""
    for name in ("cerebrofy_who", "cerebrofy_conflicts"):
        assert SPEC_BY_NAME[name].inject is True


@pytest.mark.parametrize(
    "tool_name", ["search_code", "get_neuron", "cerebrofy_remember"]
)
def test_agent_aware_tools_accept_agent_id(tool_name: str) -> None:
    agent_schema = SPEC_BY_NAME[tool_name].input_schema["properties"]["agent_id"]
    assert agent_schema["type"] == "string"
    assert "agent" in agent_schema["description"].lower()


# ---------------------------------------------------------------------------
# Dispatch / handler wiring (requires the mcp extra)
# ---------------------------------------------------------------------------


def test_all_handlers_resolve_in_server() -> None:
    """Every spec's handler_name resolves to a real callable in server._HANDLERS."""
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    assert len(server_mod._HANDLERS) == 39
    for spec in TOOL_SPECS:
        handler = server_mod._HANDLERS.get(spec.handler_name)
        assert handler is not None, f"missing handler {spec.handler_name} for {spec.name}"
        assert callable(handler)


def test_dispatch_tool_unknown_returns_unknown_error() -> None:
    pytest.importorskip("mcp")
    from mcp.types import TextContent

    from cerebrofy.mcp import server as server_mod

    result = asyncio.run(server_mod.dispatch_tool("does_not_exist", {}))

    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert result[0].type == "text"
    assert result[0].text == "Unknown tool: does_not_exist"


def test_dispatch_tool_unknown_with_args_also_unknown(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown tools short-circuit before any repo-root resolution, so they must
    not depend on a project root."""
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    # No repo here — proves the unknown path does not call require_repo_root.
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    result = asyncio.run(server_mod.dispatch_tool("zzz", {"any": "args"}))
    assert len(result) == 1
    assert result[0].text == "Unknown tool: zzz"


def test_dispatch_tool_invokes_handler_with_normalized_args(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inject=False tool routes straight to its handler with ``arguments or {}``."""
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    received: list[dict[str, object]] = []

    def _fake_handler(arguments: dict[str, object]) -> list[object]:
        received.append(arguments)
        return [{"type": "text", "text": "from-fake"}]

    # cerebrofy_build is inject=False, so no repo-root resolution occurs.
    spec = SPEC_BY_NAME["cerebrofy_build"]
    monkeypatch.setitem(server_mod._HANDLERS, spec.handler_name, _fake_handler)

    result = asyncio.run(server_mod.dispatch_tool(spec.name, {"path": "src/x.py"}))

    assert received == [{"path": "src/x.py"}]
    assert result == [{"type": "text", "text": "from-fake"}]


def test_dispatch_tool_normalizes_none_arguments(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """``arguments=None`` normalizes to ``{}`` before reaching the handler."""
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    received: list[dict[str, object]] = []

    def _fake_handler(arguments: dict[str, object]) -> list[object]:
        received.append(arguments)
        return [{"type": "text", "text": "ok"}]

    spec = SPEC_BY_NAME["cerebrofy_update"]
    monkeypatch.setitem(server_mod._HANDLERS, spec.handler_name, _fake_handler)

    asyncio.run(server_mod.dispatch_tool(spec.name, None))

    assert received == [{}]


def test_dispatch_tool_unknown_name_not_in_handlers(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown names must not raise even if _HANDLERS is empty."""
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    monkeypatch.setattr(server_mod, "_HANDLERS", {})
    result = asyncio.run(server_mod.dispatch_tool("ghost", {}))
    assert result[0].text == "Unknown tool: ghost"
