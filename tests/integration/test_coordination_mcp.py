"""Integration tests for the multi-agent coordination MCP surface (Idea #25).

Covers the catalog wiring, the five coordination tools end-to-end through
``dispatch_tool``, the dispatch-time heartbeat, and the additive middleware
used by ``get_neuron`` / ``remember``.

The tests use a throw-away project (``tmp_path``) with a real
``.cerebrofy/db/cerebrofy.db`` so registry state persists exactly as it does
for two cooperating agents. No index build and no model download is needed.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from cerebrofy.mcp.tool_specs import SPEC_BY_NAME

pytest.importorskip("mcp")
mcp_types = pytest.importorskip("mcp.types")
TextContent = mcp_types.TextContent
server_mod = pytest.importorskip("cerebrofy.mcp.server")
coordination_tools = pytest.importorskip("cerebrofy.mcp.tools.coordination")

COORDINATION_TOOLS = {
    "cerebrofy_claim": ("_handle_claim", {"agent_id", "neurons", "intent"}, False),
    "cerebrofy_release": ("_handle_release", {"agent_id"}, False),
    "cerebrofy_who": ("_handle_who", set(), True),
    "cerebrofy_conflicts": ("_handle_conflicts", set(), True),
    "cerebrofy_resolve": ("_handle_resolve", {"memory_a", "memory_b", "strategy"}, False),
}

NEURON = "src/auth/tokens.py::validate_token"
OTHER_NEURON = "src/billing/invoice.py::total"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _create_index_db(root: Path) -> None:
    """Materialise a real index DB (tools must never create it themselves)."""
    from cerebrofy.db.connection import open_db
    from cerebrofy.db.schema import create_schema

    conn = open_db(root / ".cerebrofy" / "db" / "cerebrofy.db")
    try:
        create_schema(conn, 0)
    finally:
        conn.close()


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".cerebrofy" / "db").mkdir(parents=True)
    (root / ".cerebrofy" / "config.yaml").write_text(
        "lobes:\n  root: .\n"
        "tracked_extensions: [.py]\n"
        "embedding_model: local\n"
        "embed_dim: 2\n",
        encoding="utf-8",
    )
    _create_index_db(root)
    return root


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _make_repo(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.delenv("CEREBROFY_ROOT", raising=False)
    monkeypatch.delenv("CEREBROFY_AGENT_ID", raising=False)
    # Pin handler root resolution to the temp project regardless of any
    # process-wide MCP root binding left by another test.
    monkeypatch.setattr(coordination_tools, "_find_root", lambda _cwd: root)
    return root


def _dispatch(name: str, arguments: dict[str, Any]) -> list[Any]:
    return asyncio.run(server_mod.dispatch_tool(name, arguments))


def _json_payload(result: list[Any]) -> dict[str, Any]:
    assert len(result) == 1, f"expected one content item, got {result!r}"
    item = result[0]
    assert isinstance(item, TextContent)
    return json.loads(item.text)


def _error_text(result: list[Any]) -> str:
    assert len(result) == 1
    item = result[0]
    assert isinstance(item, TextContent)
    return item.text


def _claim(
    agent_id: str,
    neurons: list[str] | None = None,
    *,
    intent: str = "refactoring auth tokens",
) -> list[Any]:
    return _dispatch(
        "cerebrofy_claim",
        {
            "agent_id": agent_id,
            "neurons": neurons or [NEURON],
            "intent": intent,
        },
    )


def _db_path(root: Path) -> Path:
    return root / ".cerebrofy" / "db" / "cerebrofy.db"


def _insert_node(root: Path, neuron_id: str = NEURON, name: str = "validate_token") -> None:
    """Insert a node so file-path expansion and get_neuron have a target."""
    file, _, _ = neuron_id.partition("::")
    db = sqlite3.connect(_db_path(root))
    try:
        db.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, name, type, file, line_start, line_end, signature, docstring) "
            "VALUES (?, ?, 'function', ?, 1, 10, 'def validate_token()', 'doc')",
            (neuron_id, name, file),
        )
        db.commit()
    finally:
        db.close()


def _write_contradicting_memories(root: Path) -> tuple[str, str]:
    from cerebrofy.memory.store import Memory, open_memories_db, write_memory

    conn = open_memories_db(root / ".cerebrofy")
    try:
        ids: list[str] = []
        for index, body in enumerate(
            ("never use datetime.now", "datetime.now is fine")
        ):
            memory_id = f"contradiction-{index}"
            write_memory(
                conn,
                Memory(
                    id=memory_id,
                    neuron_id=NEURON,
                    lobe="auth",
                    type="decision",
                    title=f"contradiction {index}",
                    body=body,
                    author=f"agent-{index}",
                    created_ts=1_700_000_000 + index,
                    tags=(),
                    decay_score=1.0,
                    status="active",
                ),
                [0.0] * 384,
            )
            ids.append(memory_id)
        conn.commit()
    finally:
        conn.close()
    return ids[0], ids[1]


def _write_memory_pair(root: Path) -> tuple[str, str]:
    """Persist two memories so resolve_pair can load them."""
    from cerebrofy.memory.store import Memory, open_memories_db, write_memory

    cerebrofy_dir = root / ".cerebrofy"
    conn = open_memories_db(cerebrofy_dir)
    try:
        ids: list[str] = []
        for index, body in enumerate(
            ("always use the rotation helper", "never use the rotation helper")
        ):
            memory_id = f"mem-{index}"
            write_memory(
                conn,
                Memory(
                    id=memory_id,
                    neuron_id=NEURON,
                    lobe="auth",
                    type="decision",
                    title=f"memory {index}",
                    body=body,
                    author=f"agent-{index}",
                    created_ts=1_700_000_000 + index,
                    tags=(),
                    decay_score=1.0,
                    status="active",
                ),
                [0.0] * 384,
            )
            ids.append(memory_id)
        conn.commit()
    finally:
        conn.close()
    return ids[0], ids[1]


# ---------------------------------------------------------------------------
# Catalog wiring
# ---------------------------------------------------------------------------


def test_coordination_tools_are_in_the_catalog() -> None:
    for name, (handler_name, required, inject) in COORDINATION_TOOLS.items():
        spec = SPEC_BY_NAME[name]
        assert spec.handler_name == handler_name
        assert spec.inject is inject
        schema = spec.input_schema
        assert schema["type"] == "object"
        assert "properties" in schema
        assert isinstance(schema["required"], list)
        assert required.issubset(set(schema["required"]))
        assert spec.description.strip()


def test_coordination_handlers_are_wired() -> None:
    for name, (handler_name, _required, _inject) in COORDINATION_TOOLS.items():
        spec = SPEC_BY_NAME[name]
        assert spec.handler_name == handler_name
        assert handler_name in server_mod._HANDLERS
        assert callable(server_mod._HANDLERS[handler_name])
        assert getattr(coordination_tools, f"handle_{name.removeprefix('cerebrofy_')}")


# ---------------------------------------------------------------------------
# Full dispatch flow
# ---------------------------------------------------------------------------


def test_claim_who_conflicts_resolve_release_flow(repo: Path) -> None:
    agent = "agent-a"

    claimed = _json_payload(_claim(agent))
    assert claimed["claimed"] == [NEURON]
    assert claimed["conflicts"] == []
    assert claimed["claim_id"]

    who = _json_payload(_dispatch("cerebrofy_who", {}))
    assert who["total_active"] == 1
    assert who["conflicts"] == []
    (row,) = who["active_agents"]
    assert row["agent_id"] == agent
    assert row["agent_type"] == "claude"
    assert row["intent"] == "refactoring auth tokens"
    assert row["claimed_neurons"] == [NEURON]
    assert isinstance(row["active_minutes"], int)
    assert "session_id" in row

    conflicts = _json_payload(_dispatch("cerebrofy_conflicts", {}))
    assert conflicts["overlapping_claims"] == []
    assert conflicts["memory_conflicts"] == []
    assert "human_review" in conflicts["resolution_options"]

    memory_a, memory_b = _write_memory_pair(repo)
    resolved = _json_payload(
        _dispatch(
            "cerebrofy_resolve",
            {
                "memory_a": memory_a,
                "memory_b": memory_b,
                "strategy": "human_review",
                "neuron": NEURON,
            },
        )
    )
    assert resolved["requires_review"] is True
    assert resolved["strategy"] == "human_review"
    assert resolved["resolved"] is False

    released = _json_payload(
        _dispatch("cerebrofy_release", {"agent_id": agent, "neurons": [NEURON]})
    )
    assert released["released"] == [NEURON]
    assert released["released_all"] is False

    who_after = _json_payload(_dispatch("cerebrofy_who", {}))
    assert who_after["total_active"] == 0


def test_second_agent_sees_claim_conflict(repo: Path) -> None:
    _claim("agent-a")
    result = _claim("agent-b", intent="editing the same token")

    text = _error_text(result)
    # Every requested neuron was already claimed: no partial claim survives.
    assert "NEURON_ALREADY_CLAIMED" in text

    who = _json_payload(_dispatch("cerebrofy_who", {}))
    assert who["total_active"] == 1
    assert who["active_agents"][0]["agent_id"] == "agent-a"


def test_all_conflicting_claim_preserves_conflict_details(repo: Path) -> None:
    _claim("agent-a", intent="refactoring auth tokens")
    result = _claim("agent-b", intent="editing the same token")

    payload = _json_payload(result)
    assert payload["error"] == "NEURON_ALREADY_CLAIMED"
    assert payload["conflicts"] == [
        {
            "neuron": NEURON,
            "existing_claimant": "agent-a",
            "claimant_intent": "refactoring auth tokens",
            "claimant_active_minutes": 0,
        }
    ]


def test_release_unknown_agent_returns_no_active_agent(repo: Path) -> None:
    result = _dispatch("cerebrofy_release", {"agent_id": "ghost", "neurons": [NEURON]})
    assert "NO_ACTIVE_AGENT" in _error_text(result)


def test_release_without_neurons_releases_all(repo: Path) -> None:
    _claim("agent-a", [NEURON, OTHER_NEURON])
    released = _json_payload(_dispatch("cerebrofy_release", {"agent_id": "agent-a"}))
    assert set(released["released"]) == {NEURON, OTHER_NEURON}
    assert released["released_all"] is True
    assert _json_payload(_dispatch("cerebrofy_who", {}))["total_active"] == 0


def test_claim_and_release_expand_file_paths(repo: Path) -> None:
    _insert_node(repo)

    claimed = _json_payload(_claim("agent-a", ["src/auth/tokens.py"]))
    assert claimed["claimed"] == [NEURON]
    assert claimed["conflicts"] == []

    released = _json_payload(
        _dispatch(
            "cerebrofy_release",
            {"agent_id": "agent-a", "neurons": ["src/auth/tokens.py"]},
        )
    )
    assert released["released"] == [NEURON]


def test_tools_return_no_index_and_never_create_the_db(repo: Path) -> None:
    _db_path(repo).unlink()

    cases: list[tuple[str, dict[str, Any]]] = [
        (
            "cerebrofy_claim",
            {"agent_id": "agent-a", "neurons": [NEURON], "intent": "edit"},
        ),
        ("cerebrofy_release", {"agent_id": "agent-a"}),
        ("cerebrofy_who", {}),
        ("cerebrofy_conflicts", {}),
        (
            "cerebrofy_resolve",
            {"memory_a": "a", "memory_b": "b", "strategy": "human_review"},
        ),
    ]

    for name, arguments in cases:
        result = _dispatch(name, arguments)
        assert "NO_INDEX" in _error_text(result), f"{name}: {result!r}"
        assert not _db_path(repo).exists(), f"{name} recreated cerebrofy.db"


def test_resolve_invalid_memory_id_is_config_error(repo: Path) -> None:
    result = _dispatch(
        "cerebrofy_resolve",
        {"memory_a": "missing-a", "memory_b": "missing-b", "strategy": "keep_newest"},
    )
    assert "CONFIG_ERROR" in _error_text(result)


# ---------------------------------------------------------------------------
# Dispatch-time heartbeat
# ---------------------------------------------------------------------------


def test_dispatch_with_agent_id_updates_last_heartbeat(repo: Path) -> None:
    _claim("agent-a")

    db = sqlite3.connect(_db_path(repo))
    try:
        # Older than the throttle window but still inside the staleness limit.
        db.execute(
            "UPDATE active_agents SET last_heartbeat = ? WHERE agent_id = 'agent-a'",
            (int(time.time()) - 120,),
        )
        db.commit()
    finally:
        db.close()

    # Any tool call carrying agent_id is a heartbeat.
    _dispatch("cerebrofy_who", {"agent_id": "agent-a"})

    db = sqlite3.connect(_db_path(repo))
    try:
        row = db.execute(
            "SELECT last_heartbeat FROM active_agents WHERE agent_id = 'agent-a'"
        ).fetchone()
    finally:
        db.close()

    assert row is not None
    assert int(row[0]) > int(time.time()) - 120


def test_dispatch_without_agent_id_does_not_open_registry(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    import cerebrofy.coordination.registry as registry_mod

    real_registry = registry_mod.ActiveAgentRegistry

    class _TrackingRegistry(real_registry):  # type: ignore[misc, valid-type]
        def __init__(self, db_path: object, **kwargs: object) -> None:
            calls.append(db_path)
            super().__init__(db_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(registry_mod, "ActiveAgentRegistry", _TrackingRegistry)

    _dispatch("cerebrofy_who", {})

    # The handler itself opens the registry once; the heartbeat must not add a
    # second opening when there is no agent_id.
    assert len(calls) == 1


def test_heartbeat_resolves_agent_id_from_environment(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _claim("agent-a")

    db = sqlite3.connect(_db_path(repo))
    try:
        # Older than the throttle window but still inside the staleness limit.
        db.execute(
            "UPDATE active_agents SET last_heartbeat = ? WHERE agent_id = 'agent-a'",
            (int(time.time()) - 120,),
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setenv("CEREBROFY_AGENT_ID", "agent-a")
    _dispatch("cerebrofy_who", {})

    db = sqlite3.connect(_db_path(repo))
    try:
        row = db.execute(
            "SELECT last_heartbeat FROM active_agents WHERE agent_id = 'agent-a'"
        ).fetchone()
    finally:
        db.close()

    assert row is not None
    assert int(row[0]) > int(time.time()) - 120


def test_heartbeat_never_creates_the_database(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _db_path(repo).unlink()
    monkeypatch.setenv("CEREBROFY_AGENT_ID", "agent-a")

    _dispatch("cerebrofy_who", {})

    assert not _db_path(repo).exists()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def _register_claim(agent_id: str, neuron: str = NEURON) -> None:
    from cerebrofy.coordination.registry import ActiveAgentRegistry

    registry = ActiveAgentRegistry(str(_db_path_for_current()))
    try:
        registry.claim_neurons(
            agent_id,
            [neuron],
            "refactoring",
            agent_type="claude",
            ttl_minutes=60,
            session_id=None,
        )
    finally:
        registry.close()


def _db_path_for_current() -> Path:
    return Path.cwd() / ".cerebrofy" / "db" / "cerebrofy.db"


def test_middleware_reports_conflict_for_other_agent(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cerebrofy.mcp import middleware

    _register_claim("agent-a")

    conflict = middleware.check_conflicts(NEURON, "agent-b")
    assert conflict["has_claim_conflict"] is True
    assert [c["agent_id"] for c in conflict["claim_conflicts"]] == ["agent-a"]
    assert conflict["has_memory_conflict"] is False

    no_conflict = middleware.check_conflicts(NEURON, "agent-a")
    assert no_conflict["has_claim_conflict"] is False
    assert no_conflict["claim_conflicts"] == []


def test_middleware_enrich_response_prepends_notice(repo: Path) -> None:
    from cerebrofy.mcp import middleware

    _register_claim("agent-a")

    original = [TextContent(type="text", text='{"neurons": []}')]
    enriched = middleware.enrich_response(original, NEURON, "agent-b")

    assert len(enriched) == 2
    notice = enriched[0]
    assert isinstance(notice, TextContent)
    assert "Claim conflict" in notice.text
    assert "agent-a" in notice.text
    assert enriched[1] is original[0]


def test_middleware_no_conflict_returns_response_unchanged(repo: Path) -> None:
    from cerebrofy.mcp import middleware

    _register_claim("agent-a")

    original = [TextContent(type="text", text="{}")]
    assert middleware.enrich_response(original, NEURON, "agent-a") is original


def test_get_neuron_enrichment_is_best_effort(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A middleware failure must never change get_neuron's normal response."""
    from cerebrofy.mcp import middleware

    def _boom(*_args: object, **_kwargs: object) -> list[Any]:
        raise RuntimeError("middleware exploded")

    monkeypatch.setattr(middleware, "enrich_response", _boom)

    result = server_mod._enrich_with_coordination(
        [TextContent(type="text", text="original")], NEURON, {"agent_id": "agent-b"}
    )
    assert [item.text for item in result] == ["original"]


def test_enrichment_requires_agent_id(repo: Path) -> None:
    """No literal 'claude' fallback: without an agent_id nothing is enriched."""
    _register_claim("agent-a")
    original = [TextContent(type="text", text='{"neurons": []}')]

    assert server_mod._enrich_with_coordination(original, NEURON, {}) is original
    assert (
        server_mod._enrich_with_coordination(original, NEURON, {"agent_id": "   "})
        is original
    )

    enriched = server_mod._enrich_with_coordination(
        original, NEURON, {"agent_id": "agent-b"}
    )
    assert len(enriched) == 2
    assert "Claim conflict" in enriched[0].text


def test_middleware_reads_while_writer_holds_lock(repo: Path) -> None:
    """Read-only middleware must return promptly under BEGIN IMMEDIATE."""
    from cerebrofy.mcp import middleware

    _register_claim("agent-a")

    blocker = sqlite3.connect(_db_path(repo), timeout=0.5)
    blocker.isolation_level = None
    try:
        blocker.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        conflict = middleware.check_conflicts(NEURON, "agent-b")
        elapsed = time.monotonic() - started
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert elapsed < 2.0
    assert conflict["has_claim_conflict"] is True
    assert [c["agent_id"] for c in conflict["claim_conflicts"]] == ["agent-a"]


def test_get_neuron_passes_memories_into_enrichment(repo: Path) -> None:
    """Two contradicting memories on a neuron produce a memory-conflict notice."""
    _insert_node(repo)
    _write_contradicting_memories(repo)

    result = _dispatch(
        "get_neuron", {"name": "validate_token", "agent_id": "agent-b"}
    )

    assert len(result) == 2
    notice = result[0]
    assert isinstance(notice, TextContent)
    assert "Memory contradiction" in notice.text
    assert "contradiction-0" in notice.text
    assert "contradiction-1" in notice.text


def test_with_epistemic_preserves_a_prepended_notice(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The epistemic footer belongs on the payload, not the coordination notice."""
    from dataclasses import dataclass

    @dataclass
    class _State:
        def to_dict(self) -> dict[str, Any]:
            return {"confidence": 1.0}

        def confidence_line(self) -> str:
            return "confidence 100%"

    monkeypatch.setattr(server_mod, "_compute_epistemic", lambda _root: _State())

    notice = TextContent(type="text", text="⚠️ Claim conflict: agent-a")
    payload = TextContent(type="text", text='{"neurons": []}')
    result = server_mod._with_epistemic([notice, payload], repo)

    assert result[0] is notice
    assert json.loads(result[1].text)["epistemic"] == {"confidence": 1.0}
