"""Integration tests for multi-agent coordination scenarios (Idea #25 follow-ups).

Covers concurrent agents, race conditions, heartbeat expiration,
cross-lobe awareness, and full MCP orchestration flows.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.db.connection import open_db
from cerebrofy.db.schema import create_schema
from cerebrofy.memory.store import Memory, open_memories_db, write_memory
from cerebrofy.utils.paths import reset_bound_root, reset_root_boundary

pytest.importorskip("mcp")
mcp_types = pytest.importorskip("mcp.types")
TextContent = mcp_types.TextContent
server_mod = pytest.importorskip("cerebrofy.mcp.server")
coordination_tools = pytest.importorskip("cerebrofy.mcp.tools.coordination")

ZERO_EMBEDDING = [0.0] * 384

NEURON_AUTH = "src/auth/tokens.py::validate_token"
NEURON_BILLING = "src/billing/invoice.py::total"
NEURON_DB = "src/db/pool.py::get_connection"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _create_index_db(root: Path) -> None:
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


def _seed_nodes(cerebrofy_dir: Path) -> None:
    conn = sqlite3.connect(str(cerebrofy_dir / "db" / "cerebrofy.db"))
    try:
        conn.execute(
            "CREATE TABLE nodes ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, file TEXT NOT NULL, "
            "type TEXT, line_start INTEGER, line_end INTEGER, signature TEXT, "
            "docstring TEXT, hash TEXT)"
        )
        conn.executemany(
            "INSERT INTO nodes(id, name, file, line_start) VALUES (?, ?, ?, ?)",
            [
                (NEURON_AUTH, "validate_token", "src/auth/tokens.py", 10),
                ("src/auth/tokens.py::refresh_token", "refresh_token", "src/auth/tokens.py", 40),
                (NEURON_BILLING, "total", "src/billing/invoice.py", 1),
                (NEURON_DB, "get_connection", "src/db/pool.py", 1),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _setup_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cerebrofy_dir = tmp_path / ".cerebrofy"
    db_dir = cerebrofy_dir / "db"
    db_dir.mkdir(parents=True)
    (cerebrofy_dir / "config.yaml").write_text(
        "lobes:\n  root: .\n", encoding="utf-8"
    )
    sqlite3.connect(str(db_dir / "cerebrofy.db")).close()

    reset_bound_root()
    reset_root_boundary()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CEREBROFY_ROOT", str(tmp_path))
    monkeypatch.delenv("CEREBROFY_AGENT_ID", raising=False)
    _seed_nodes(cerebrofy_dir)
    return cerebrofy_dir


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _make_repo(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.delenv("CEREBROFY_ROOT", raising=False)
    monkeypatch.delenv("CEREBROFY_AGENT_ID", raising=False)
    monkeypatch.setattr(coordination_tools, "_find_root", lambda _cwd: root)
    _insert_nodes(root)
    return root


def _insert_nodes(root: Path) -> None:
    conn = sqlite3.connect(root / ".cerebrofy" / "db" / "cerebrofy.db")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nodes ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, file TEXT NOT NULL, "
            "type TEXT, line_start INTEGER, line_end INTEGER, signature TEXT, "
            "docstring TEXT, hash TEXT)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO nodes(id, name, file, line_start) VALUES (?, ?, ?, ?)",
            [
                (NEURON_AUTH, "validate_token", "src/auth/tokens.py", 10),
                ("src/auth/tokens.py::refresh_token", "refresh_token", "src/auth/tokens.py", 40),
                (NEURON_BILLING, "total", "src/billing/invoice.py", 1),
                (NEURON_DB, "get_connection", "src/db/pool.py", 1),
            ],
        )
        conn.commit()
    finally:
        conn.close()


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
    intent: str = "refactoring",
) -> list[Any]:
    return _dispatch(
        "cerebrofy_claim",
        {
            "agent_id": agent_id,
            "neurons": neurons or [NEURON_AUTH],
            "intent": intent,
        },
    )


def _invoke(args: list[str]) -> Any:
    return CliRunner().invoke(main, args)


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _write_memory_pair(root: Path) -> tuple[str, str]:
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
                    neuron_id=NEURON_AUTH,
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


def _write_contradicting_memories(root: Path) -> tuple[str, str]:
    cerebrofy_dir = root / ".cerebrofy"
    conn = open_memories_db(cerebrofy_dir)
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
                    neuron_id=NEURON_AUTH,
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


# ---------------------------------------------------------------------------
# Concurrent claims / race conditions
# ---------------------------------------------------------------------------


def test_concurrent_claims_one_wins(repo: Path) -> None:
    """Two agents claim the same neuron simultaneously; one wins, one gets conflict."""
    # First agent claims
    claimed_a = _json_payload(_claim("agent-a", intent="refactor auth"))
    assert claimed_a["claimed"] == [NEURON_AUTH]

    # Second agent tries to claim same neuron
    result_b = _claim("agent-b", intent="fix bug in auth")
    assert "NEURON_ALREADY_CLAIMED" in _error_text(result_b)

    # Verify only agent-a has the claim
    who = _json_payload(_dispatch("cerebrofy_who", {}))
    assert who["total_active"] == 1
    assert who["active_agents"][0]["agent_id"] == "agent-a"


def test_claim_transfer_after_release(repo: Path) -> None:
    """Agent A releases, Agent B can immediately claim the same neuron."""
    _claim("agent-a")
    _json_payload(_dispatch("cerebrofy_release", {"agent_id": "agent-a", "neurons": [NEURON_AUTH]}))

    claimed_b = _json_payload(_claim("agent-b", intent="take over"))
    assert claimed_b["claimed"] == [NEURON_AUTH]

    who = _json_payload(_dispatch("cerebrofy_who", {}))
    assert who["total_active"] == 1
    assert who["active_agents"][0]["agent_id"] == "agent-b"


def test_three_agents_overlapping_claims(repo: Path) -> None:
    """Three agents with overlapping but not identical claim sets.

    To create true overlapping claims, agents must claim non-conflicting neurons
    first, then expand into overlapping territory.
    """
    # agent-a claims auth
    _claim("agent-a", [NEURON_AUTH], intent="auth")
    # agent-b claims billing
    _claim("agent-b", [NEURON_BILLING], intent="billing")
    # agent-c claims db
    _claim("agent-c", [NEURON_DB], intent="db")

    # Now agent-a expands to also claim billing (overlaps with agent-b)
    result_a2 = _claim("agent-a", [NEURON_BILLING], intent="auth + billing")
    assert "NEURON_ALREADY_CLAIMED" in _error_text(result_a2)

    # agent-b expands to claim auth (overlaps with agent-a)
    result_b2 = _claim("agent-b", [NEURON_AUTH], intent="billing + auth")
    assert "NEURON_ALREADY_CLAIMED" in _error_text(result_b2)

    # Now both agent-a and agent-b hold their original neurons
    # overlapping_claims should be empty since no neuron is claimed by multiple agents
    conflicts = _json_payload(_dispatch("cerebrofy_conflicts", {}))
    overlapping = conflicts["overlapping_claims"]
    assert overlapping == []

    # Now test true overlapping: release and re-claim with race
    _json_payload(_dispatch("cerebrofy_release", {"agent_id": "agent-a", "neurons": [NEURON_AUTH]}))
    _json_payload(_dispatch("cerebrofy_release", {"agent_id": "agent-b", "neurons": [NEURON_BILLING]}))

    # Both claim the same neuron
    claimed_a = _json_payload(_claim("agent-a", [NEURON_AUTH], intent="auth"))
    claimed_b = _json_payload(_claim("agent-b", [NEURON_AUTH], intent="billing wants auth"))
    # One should succeed, one should fail
    success_count = sum(1 for c in (claimed_a, claimed_b) if c.get("claimed"))
    assert success_count == 1


# ---------------------------------------------------------------------------
# Heartbeat expiration
# ---------------------------------------------------------------------------


def test_stale_agent_claim_expires(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An agent past the staleness threshold loses its claims."""
    from cerebrofy.coordination.registry import ActiveAgentRegistry

    registry = ActiveAgentRegistry(str(repo / ".cerebrofy" / "db" / "cerebrofy.db"))
    try:
        registry.claim_neurons(
            "agent-stale",
            [NEURON_AUTH],
            "old work",
            agent_type="claude",
            ttl_minutes=1,
            session_id=None,
        )
        # Manually age the heartbeat past staleness threshold (2 * heartbeat_interval = 600s)
        # Also age expires_ts past TTL
        db = sqlite3.connect(repo / ".cerebrofy" / "db" / "cerebrofy.db")
        try:
            now = int(time.time())
            db.execute(
                "UPDATE active_agents SET last_heartbeat = ?, expires_ts = ? WHERE agent_id = 'agent-stale'",
                (now - 700, now - 100),  # 700s ago for heartbeat, 100s ago for TTL
            )
            db.commit()
        finally:
            db.close()
    finally:
        registry.close()

    # Stale agent should not block new claims
    claimed = _json_payload(_claim("agent-fresh", intent="new work"))
    assert claimed["claimed"] == [NEURON_AUTH]
    assert claimed["conflicts"] == []

    who = _json_payload(_dispatch("cerebrofy_who", {}))
    # Stale agent should be cleaned up
    active_ids = {a["agent_id"] for a in who["active_agents"]}
    assert "agent-stale" not in active_ids
    assert "agent-fresh" in active_ids


# ---------------------------------------------------------------------------
# Memory contradiction resolution - all strategies
# ---------------------------------------------------------------------------


def test_resolve_keep_newest_via_cli(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = repo / ".cerebrofy"
    old_id, new_id = _write_memory_pair(repo)

    payload = _payload(
        _invoke(["resolve", old_id, new_id, "--format", "json"])
    )

    assert payload["resolved"] is True
    assert payload["strategy"] == "keep_newest"
    assert payload["winner"] == new_id

    conn = open_memories_db(cerebrofy_dir)
    try:
        from cerebrofy.memory.store import get_memory
        assert get_memory(conn, old_id).status == "stale"  # type: ignore[union-attr]
        assert get_memory(conn, new_id).status == "active"  # type: ignore[union-attr]
    finally:
        conn.close()


def test_resolve_keep_by_author_via_cli(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    mem_a, mem_b = _write_memory_pair(repo)
    # mem_a author = agent-0, mem_b author = agent-1

    payload = _payload(
        _invoke(["resolve", mem_a, mem_b, "--keep", "author", "--author", "agent-0", "--format", "json"])
    )

    assert payload["resolved"] is True
    assert payload["strategy"] == "keep_by_author"
    assert payload["winner"] == mem_a


def test_resolve_human_review_via_cli(repo: Path) -> None:
    mem_a, mem_b = _write_memory_pair(repo)

    payload = _payload(
        _invoke(["resolve", mem_a, mem_b, "--keep", "human-review", "--format", "json"])
    )

    assert payload["resolved"] is False
    assert payload["requires_review"] is True
    assert payload["strategy"] == "human_review"


def test_resolve_merge_via_cli(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    mem_a, mem_b = _write_memory_pair(repo)

    payload = _payload(
        _invoke(
            [
                "resolve",
                mem_a,
                mem_b,
                "--merge",
                "--body",
                "Use the rotation helper with timezone awareness.",
                "--author",
                "human",
                "--format",
                "json",
            ]
        )
    )

    assert payload["strategy"] == "merge"
    assert payload["superseded"] == [mem_a, mem_b]
    assert payload["winner"].startswith("mem_")
    assert "merged_memory" in payload


def test_resolve_all_strategies_via_mcp(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    mem_a, mem_b = _write_memory_pair(repo)

    for strategy in ("keep_newest", "keep_by_author", "human_review", "merge"):
        args = {
            "memory_a": mem_a,
            "memory_b": mem_b,
            "strategy": strategy,
            "neuron": NEURON_AUTH,
        }
        if strategy == "keep_by_author":
            args["author"] = "agent-0"
        if strategy == "merge":
            args["merged_body"] = "Merged resolution"
            args["author"] = "human"

        result = _dispatch("cerebrofy_resolve", args)
        payload = _json_payload(result)

        if strategy == "human_review":
            assert payload["resolved"] is False
            assert payload["requires_review"] is True
        else:
            assert payload["resolved"] is True
            assert payload["strategy"] == strategy


# ---------------------------------------------------------------------------
# Cross-lobe awareness
# ---------------------------------------------------------------------------


def test_cross_lobe_awareness_notifications(repo: Path) -> None:
    """Agents claiming neurons in the same lobe see each other."""
    _claim("agent-a", [NEURON_AUTH], intent="auth work")
    # agent-b claims a different neuron in the same lobe
    _claim("agent-b", ["src/auth/tokens.py::refresh_token"], intent="auth work too")

    who = _json_payload(_dispatch("cerebrofy_who", {}))
    assert who["total_active"] == 2

    # cerebrofy_who does not take a neuron argument; cross-lobe awareness is
    # exposed through the middleware instead.
    from cerebrofy.mcp import middleware

    awareness = middleware.check_conflicts(NEURON_AUTH, "agent-a")
    assert awareness["has_lobe_activity"] is True
    assert [a["agent_id"] for a in awareness["lobe_awareness"]] == ["agent-b"]


def test_cross_lobe_awareness_different_lobes_no_notice(repo: Path) -> None:
    """Agents in different lobes don't get awareness for each other."""
    _claim("agent-a", [NEURON_AUTH], intent="auth")
    _claim("agent-b", [NEURON_BILLING], intent="billing")

    conflicts = _json_payload(_dispatch("cerebrofy_conflicts", {}))
    assert conflicts["overlapping_claims"] == []


# ---------------------------------------------------------------------------
# Full MCP orchestration flow
# ---------------------------------------------------------------------------


def test_full_mcp_orchestration_flow(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: claim -> work -> detect conflicts -> resolve -> release."""
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )

    # 1. Agent A claims
    claimed = _json_payload(_claim("agent-a", intent="refactor auth validation"))
    assert claimed["claimed"] == [NEURON_AUTH]

    # 2. Agent B tries to claim same neuron - gets conflict
    result_b = _claim("agent-b", intent="add logging to auth")
    assert "NEURON_ALREADY_CLAIMED" in _error_text(result_b)

    # 3. Agent B checks conflicts - should see claim conflict
    conflicts = _json_payload(_dispatch("cerebrofy_conflicts", {}))
    # No overlapping claims (agent-b didn't get the claim)
    assert conflicts["overlapping_claims"] == []
    # But agent-b can check specific neuron for claim conflicts
    from cerebrofy.mcp import middleware
    conflict = middleware.check_conflicts(NEURON_AUTH, "agent-b")
    assert conflict["has_claim_conflict"] is True
    assert [c["agent_id"] for c in conflict["claim_conflicts"]] == ["agent-a"]

    # 4. Agent A does work, writes a memory (matches "always use X" pattern)
    cerebrofy_dir = repo / ".cerebrofy"
    conn = open_memories_db(cerebrofy_dir)
    try:
        write_memory(
            conn,
            Memory(
                id="mem-agent-a-work",
                neuron_id=NEURON_AUTH,
                lobe="auth",
                type="decision",
                title="validation approach",
                body="always use rotation_helper",
                author="agent-a",
                created_ts=int(time.time()),
                tags=(),
                decay_score=1.0,
                status="active",
            ),
            ZERO_EMBEDDING,
        )
        conn.commit()
    finally:
        conn.close()

    # 5. Agent B writes contradicting memory (matches "X is not required" pattern)
    conn = open_memories_db(cerebrofy_dir)
    try:
        write_memory(
            conn,
            Memory(
                id="mem-agent-b-work",
                neuron_id=NEURON_AUTH,
                lobe="auth",
                type="decision",
                title="validation approach",
                body="rotation_helper is not required",
                author="agent-b",
                created_ts=int(time.time()) + 1,
                tags=(),
                decay_score=1.0,
                status="active",
            ),
            ZERO_EMBEDDING,
        )
        conn.commit()
    finally:
        conn.close()

    # 6. Detect memory conflicts via conflicts tool
    conflicts = _json_payload(_dispatch("cerebrofy_conflicts", {}))
    assert len(conflicts["memory_conflicts"]) == 1
    mem_conflict = conflicts["memory_conflicts"][0]
    assert mem_conflict["neuron"] == NEURON_AUTH

    # 7. Resolve via merge (human decision)
    resolved = _json_payload(
        _dispatch(
            "cerebrofy_resolve",
            {
                "memory_a": "mem-agent-a-work",
                "memory_b": "mem-agent-b-work",
                "strategy": "merge",
                "neuron": NEURON_AUTH,
                "merged_body": "Use rotation helper for tokens, direct validation for sessions",
                "author": "human-reviewer",
            },
        )
    )
    assert resolved["strategy"] == "merge"
    assert resolved["superseded"] == ["mem-agent-a-work", "mem-agent-b-work"]
    assert resolved["winner"].startswith("mem_")

    # 8. Agent A releases
    released = _json_payload(
        _dispatch("cerebrofy_release", {"agent_id": "agent-a", "neurons": [NEURON_AUTH]})
    )
    assert released["released"] == [NEURON_AUTH]

    # 9. Verify clean state
    who = _json_payload(_dispatch("cerebrofy_who", {}))
    assert who["total_active"] == 0


# ---------------------------------------------------------------------------
# Middleware integration with multiple agents
# ---------------------------------------------------------------------------


def test_middleware_enriches_for_multiple_waiting_agents(repo: Path) -> None:
    """Multiple waiting agents all get conflict notices."""
    from cerebrofy.mcp import middleware

    _claim("agent-a", [NEURON_AUTH], intent="primary")
    _claim("agent-b", [NEURON_BILLING], intent="secondary")

    # Both agent-c and agent-d check the same neuron
    conflict_c = middleware.check_conflicts(NEURON_AUTH, "agent-c")
    conflict_d = middleware.check_conflicts(NEURON_AUTH, "agent-d")

    assert conflict_c["has_claim_conflict"] is True
    assert conflict_d["has_claim_conflict"] is True
    assert [c["agent_id"] for c in conflict_c["claim_conflicts"]] == ["agent-a"]
    assert [c["agent_id"] for c in conflict_d["claim_conflicts"]] == ["agent-a"]


def test_middleware_memory_conflict_notice(repo: Path) -> None:
    """Middleware detects memory contradictions when memories are provided."""
    import asyncio

    from cerebrofy.mcp import middleware
    from cerebrofy.mcp.server import dispatch_tool

    _write_contradicting_memories(repo)

    # First, get the memories via MCP to see the structure
    # The middleware check_conflicts requires memories to be passed explicitly
    # Get memories using get_neuron
    result = asyncio.run(dispatch_tool("get_neuron", {"name": "validate_token", "agent_id": "agent-new"}))
    assert len(result) >= 1

    # Now test middleware with memories passed explicitly
    # We need to extract memories from the response
    # For now, test that without memories, has_memory_conflict is False
    conflict = middleware.check_conflicts(NEURON_AUTH, "agent-new")
    assert conflict["has_memory_conflict"] is False

    # With memories, it should detect conflicts
    memories = [
        {"id": "contradiction-0", "body": "never use datetime.now", "author": "agent-0"},
        {"id": "contradiction-1", "body": "datetime.now is fine", "author": "agent-1"},
    ]
    conflict_with_memories = middleware.check_conflicts(NEURON_AUTH, "agent-new", memories=memories)
    assert conflict_with_memories["has_memory_conflict"] is True
    assert len(conflict_with_memories["memory_conflicts"]) == 1


# ---------------------------------------------------------------------------
# CLI: coordination group alias works for all commands
# ---------------------------------------------------------------------------


def test_coordination_group_alias_all_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_repo(tmp_path, monkeypatch)

    # who
    payload = _payload(_invoke(["coordination", "who", "--format", "json"]))
    assert payload["total_active"] == 0

    # claim
    payload = _payload(
        _invoke(
            [
                "coordination",
                "claim",
                NEURON_AUTH,
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )
    assert payload["claimed"] == [NEURON_AUTH]

    # conflicts
    payload = _payload(_invoke(["coordination", "conflicts", "--format", "json"]))
    assert "memory_conflicts" in payload
    assert "overlapping_claims" in payload

    # release
    payload = _payload(
        _invoke(
            [
                "coordination",
                "release",
                NEURON_AUTH,
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )
    assert payload["released"] == [NEURON_AUTH]


# ---------------------------------------------------------------------------
# Error handling edge cases
# ---------------------------------------------------------------------------


def test_resolve_nonexistent_memory_fails(repo: Path) -> None:
    result = _dispatch(
        "cerebrofy_resolve",
        {"memory_a": "nonexistent-a", "memory_b": "nonexistent-b", "strategy": "keep_newest"},
    )
    assert "CONFIG_ERROR" in _error_text(result)


def test_resolve_same_memory_id_fails(repo: Path) -> None:
    mem_a, _mem_b = _write_memory_pair(repo)
    result = _dispatch(
        "cerebrofy_resolve",
        {"memory_a": mem_a, "memory_b": mem_a, "strategy": "keep_newest"},
    )
    # Error message says they must be different, not CONFIG_ERROR code
    assert "must be different" in _error_text(result)


def test_claim_invalid_neuron_accepted(repo: Path) -> None:
    """Claiming a neuron not in the index is accepted (claims are by ID, not validated against index)."""
    claimed = _json_payload(_claim("agent-a", ["nonexistent/neuron::foo"]))
    assert claimed["claimed"] == ["nonexistent/neuron::foo"]
    assert claimed["conflicts"] == []


def test_release_nonexistent_agent_fails(repo: Path) -> None:
    result = _dispatch("cerebrofy_release", {"agent_id": "ghost", "neurons": [NEURON_AUTH]})
    assert "NO_ACTIVE_AGENT" in _error_text(result)


# ---------------------------------------------------------------------------
# Concurrent MCP tool calls
# ---------------------------------------------------------------------------


def test_concurrent_mcp_calls_serialized_by_db(repo: Path) -> None:
    """Multiple concurrent tool calls don't corrupt the registry."""
    import threading

    results: list[Any] = []

    def claim_worker(agent_id: str) -> None:
        result = _dispatch(
            "cerebrofy_claim",
            {"agent_id": agent_id, "neurons": [NEURON_AUTH], "intent": "test"},
        )
        results.append((agent_id, result))

    threads = [
        threading.Thread(target=claim_worker, args=(f"agent-{i}",))
        for i in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one should succeed.
    success_count = 0
    for _, result in results:
        try:
            payload = _json_payload(result)
            if payload.get("claimed"):
                success_count += 1
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")
    assert success_count == 1

    # Cleanup
    who = _json_payload(_dispatch("cerebrofy_who", {}))
    if who["total_active"] > 0:
        _dispatch("cerebrofy_release", {"agent_id": who["active_agents"][0]["agent_id"]})