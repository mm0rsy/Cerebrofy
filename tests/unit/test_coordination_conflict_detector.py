"""Unit tests for multi-agent claim and memory conflict detection (Idea #25)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from cerebrofy.coordination.conflict_detector import ConflictDetector
from cerebrofy.coordination.registry import ActiveAgentRegistry
from cerebrofy.db.schema import create_schema
from cerebrofy.memory.store import Memory, open_memories_db, write_memory


def _registry(tmp_path: Path) -> ActiveAgentRegistry:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    try:
        create_schema(conn, 0)
    finally:
        conn.close()
    return ActiveAgentRegistry(db_path)


def _pair(
    body_a: str, body_b: str
) -> list[dict[str, Any]]:
    return [
        {"id": "mem_a", "body": body_a, "author": "agent-a"},
        {"id": "mem_b", "body": body_b, "author": "agent-b"},
    ]


def test_never_vs_fine_pair_fires() -> None:
    detector = ConflictDetector()
    conflicts = detector.detect_memory_contradictions(
        "auth/tokens.py::validate_token",
        _pair(
            "Never use datetime.now() for timestamps",
            "datetime.now() is fine here",
        ),
    )
    assert len(conflicts) == 1
    assert conflicts[0]["memory_a"]["id"] == "mem_a"
    assert conflicts[0]["memory_b"]["id"] == "mem_b"
    assert conflicts[0]["resolution_options"] == [
        "keep_newest",
        "keep_by_author",
        "human_review",
        "merge",
    ]


def test_always_vs_not_required_pair_fires() -> None:
    detector = ConflictDetector()
    conflicts = detector.detect_memory_contradictions(
        "models/user.py::User",
        _pair(
            "Always use dataclasses for value objects",
            "dataclasses is not required",
        ),
    )
    assert len(conflicts) == 1


def test_deprecated_vs_recommended_pair_fires() -> None:
    detector = ConflictDetector()
    conflicts = detector.detect_memory_contradictions(
        "api/client.py::Client",
        _pair("This API is deprecated", "This API is recommended"),
    )
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "keyword_opposition"


def test_non_contradictory_pair_does_not_fire() -> None:
    detector = ConflictDetector()
    conflicts = detector.detect_memory_contradictions(
        "docs/readme.py::main",
        _pair(
            "Use dataclasses for value objects",
            "Tests live under tests/unit",
        ),
    )
    assert conflicts == []


def test_duplicate_pairs_are_deduped() -> None:
    detector = ConflictDetector()
    memories = _pair(
        "Never use datetime.now() for timestamps",
        "datetime.now() is fine here",
    )
    # The same memory appears twice; only one unordered pair may be reported.
    conflicts = detector.detect_memory_contradictions(
        "auth/tokens.py::validate_token", [*memories, memories[0]]
    )
    assert len(conflicts) == 1


def test_claim_conflict_excludes_requester(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    try:
        registry.claim_neurons("agent-1", ["neuron-a"], "work")
        detector = ConflictDetector(registry)

        mine = detector.detect_claim_conflicts("neuron-a", "agent-1")
        theirs = detector.detect_claim_conflicts("neuron-a", "agent-2")

        assert mine["has_conflict"] is False
        assert mine["claiming_agents"] == []
        assert theirs["has_conflict"] is True
        assert theirs["claiming_agents"][0]["agent_id"] == "agent-1"
        # Alias retained for the MCP middleware hook.
        assert theirs["claim_conflicts"] == theirs["claiming_agents"]
    finally:
        registry.close()


def test_lobe_awareness_lists_other_agents(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    try:
        registry.claim_neurons("agent-1", ["auth/tokens.py::refresh"], "work")
        registry.claim_neurons("agent-2", ["billing/invoice.py::total"], "other")
        detector = ConflictDetector(registry)

        awareness = detector.detect_lobe_awareness(
            "auth/tokens.py::validate_token", "agent-2"
        )
        assert [agent["agent_id"] for agent in awareness] == ["agent-1"]
    finally:
        registry.close()


def _seed_memories_db(cerebrofy_dir: Path) -> None:
    (cerebrofy_dir / "db").mkdir(parents=True, exist_ok=True)
    conn = open_memories_db(cerebrofy_dir)
    try:
        write_memory(
            conn,
            Memory(
                id="mem_conflict_a",
                neuron_id="auth/tokens.py::validate_token",
                lobe="auth",
                type="warning",
                title="Avoid datetime.now",
                body="Never use datetime.now() for timestamps",
                author="agent-a",
                created_ts=1000,
                tags=(),
                decay_score=1.0,
                status="active",
            ),
            [0.0] * 384,
        )
        write_memory(
            conn,
            Memory(
                id="mem_conflict_b",
                neuron_id="auth/tokens.py::validate_token",
                lobe="auth",
                type="context",
                title="datetime is safe",
                body="datetime.now() is fine here",
                author="agent-b",
                created_ts=2000,
                tags=(),
                decay_score=1.0,
                status="active",
            ),
            [0.0] * 384,
        )
        write_memory(
            conn,
            Memory(
                id="mem_plain",
                neuron_id="docs/readme.py::main",
                lobe="docs",
                type="context",
                title="Docs",
                body="Documentation lives in docs/",
                author="agent-a",
                created_ts=3000,
                tags=(),
                decay_score=1.0,
                status="active",
            ),
            [0.0] * 384,
        )
        conn.commit()
    finally:
        conn.close()


def test_memory_conflicts_loaded_from_memories_db(tmp_path: Path) -> None:
    cerebrofy_dir = tmp_path / ".cerebrofy"
    _seed_memories_db(cerebrofy_dir)

    detector = ConflictDetector(
        None, memories_db_path=cerebrofy_dir / "db" / "memories.db"
    )
    conflicts = detector.detect_memory_conflicts()

    assert len(conflicts) == 1
    assert conflicts[0]["neuron"] == "auth/tokens.py::validate_token"
    assert {conflicts[0]["memory_a"]["id"], conflicts[0]["memory_b"]["id"]} == {
        "mem_conflict_a",
        "mem_conflict_b",
    }

    assert detector.detect_memory_conflicts("missing/neuron.py::nope") == []


def test_memory_conflicts_missing_db_returns_empty(tmp_path: Path) -> None:
    detector = ConflictDetector(
        None, memories_db_path=tmp_path / "does-not-exist.db"
    )
    assert detector.detect_memory_conflicts() == []


def test_missing_cerebrofy_path_is_treated_as_directory(tmp_path: Path) -> None:
    cerebrofy_dir = tmp_path / ".cerebrofy"
    detector = ConflictDetector(None, memories_db_path=cerebrofy_dir)

    # Must resolve to ``.cerebrofy/db/memories.db`` (absent), not create a
    # bogus ``.cerebrofy`` SQLite file.
    assert detector.detect_memory_conflicts() == []
    assert not cerebrofy_dir.exists()


def test_possibly_stale_memories_are_included(tmp_path: Path) -> None:
    cerebrofy_dir = tmp_path / ".cerebrofy"
    _seed_memories_db(cerebrofy_dir)

    conn = sqlite3.connect(str(cerebrofy_dir / "db" / "memories.db"))
    try:
        conn.execute(
            "UPDATE memories SET status = 'possibly_stale' WHERE id = ?",
            ("mem_conflict_a",),
        )
        conn.commit()
    finally:
        conn.close()

    detector = ConflictDetector(
        None, memories_db_path=cerebrofy_dir / "db" / "memories.db"
    )
    assert len(detector.detect_memory_conflicts()) == 1
