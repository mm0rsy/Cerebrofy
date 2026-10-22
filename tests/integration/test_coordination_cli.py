"""Integration tests for the multi-agent coordination CLI (Idea #25)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.errors import NEURON_ALREADY_CLAIMED, NO_ACTIVE_AGENT
from cerebrofy.memory.store import Memory, get_memory, open_memories_db, write_memory
from cerebrofy.utils.paths import reset_bound_root, reset_root_boundary

ZERO_EMBEDDING = [0.0] * 384


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
    return cerebrofy_dir


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
                (
                    "auth/tokens.py::validate_token",
                    "validate_token",
                    "auth/tokens.py",
                    10,
                ),
                (
                    "auth/tokens.py::refresh_token",
                    "refresh_token",
                    "auth/tokens.py",
                    40,
                ),
                ("auth/users.py::User", "User", "auth/users.py", 1),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _seed_memories(cerebrofy_dir: Path) -> tuple[str, str]:
    conn = open_memories_db(cerebrofy_dir)
    try:
        for memory_id, created_ts, author, body in (
            (
                "mem_conflict_old",
                1000,
                "alice",
                "Never use datetime.now() for timestamps",
            ),
            (
                "mem_conflict_new",
                2000,
                "bob",
                "datetime.now() is fine here",
            ),
        ):
            write_memory(
                conn,
                Memory(
                    id=memory_id,
                    neuron_id="auth/tokens.py::validate_token",
                    lobe="auth",
                    type="warning",
                    title=memory_id,
                    body=body,
                    author=author,
                    created_ts=created_ts,
                    tags=(),
                    decay_score=1.0,
                    status="active",
                ),
                ZERO_EMBEDDING,
            )
        conn.commit()
    finally:
        conn.close()
    return "mem_conflict_old", "mem_conflict_new"


def _invoke(args: list[str]) -> Any:
    return CliRunner().invoke(main, args)


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    return cast(dict[str, Any], json.loads(result.output))


def test_who_json_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_repo(tmp_path, monkeypatch)

    payload = _payload(_invoke(["who", "--format", "json"]))

    assert payload == {"active_agents": [], "conflicts": [], "total_active": 0}


def test_claim_expands_file_path_to_all_neurons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    _seed_nodes(cerebrofy_dir)

    payload = _payload(
        _invoke(
            [
                "claim",
                "auth/tokens.py",
                "--intent",
                "refactoring token validation",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    assert payload["claimed"] == [
        "auth/tokens.py::validate_token",
        "auth/tokens.py::refresh_token",
    ]

    who = _payload(_invoke(["who", "--format", "json"]))
    assert who["total_active"] == 1
    assert who["active_agents"][0]["agent_id"] == "agent-1"
    assert who["active_agents"][0]["claimed_neurons"] == payload["claimed"]


def test_claim_conflict_returns_details_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    first = _payload(
        _invoke(
            [
                "claim",
                "n1",
                "--intent",
                "first",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )
    assert first["claimed"] == ["n1"]

    blocked = _invoke(
        [
            "claim",
            "n1",
            "--intent",
            "second",
            "--agent-id",
            "agent-2",
            "--format",
            "json",
        ]
    )

    assert blocked.exit_code == 1
    payload = json.loads(blocked.output)
    assert payload["claimed"] == []
    assert payload["error"] == NEURON_ALREADY_CLAIMED
    assert payload["claim_id"]
    assert payload["conflicts"] == [
        {
            "neuron": "n1",
            "existing_claimant": "agent-1",
            "claimant_intent": "first",
            "claimant_active_minutes": 0,
        }
    ]


def test_claim_conflict_text_lists_claimant_and_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    _payload(
        _invoke(
            [
                "claim",
                "n1",
                "--intent",
                "first",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    blocked = _invoke(
        [
            "claim",
            "n1",
            "--intent",
            "second",
            "--agent-id",
            "agent-2",
        ]
    )

    assert blocked.exit_code == 1
    assert "n1" in blocked.output
    assert "agent-1" in blocked.output
    assert "first" in blocked.output
    assert f"Error: [{NEURON_ALREADY_CLAIMED}]" in blocked.output


def test_claim_absolute_file_path_is_normalised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    _seed_nodes(cerebrofy_dir)

    payload = _payload(
        _invoke(
            [
                "claim",
                str(tmp_path / "auth" / "tokens.py"),
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    assert payload["claimed"] == [
        "auth/tokens.py::validate_token",
        "auth/tokens.py::refresh_token",
    ]


def test_claim_literal_neuron_id_is_not_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    _seed_nodes(cerebrofy_dir)

    payload = _payload(
        _invoke(
            [
                "claim",
                "auth/tokens.py::validate_token",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    assert payload["claimed"] == ["auth/tokens.py::validate_token"]


def test_claim_without_intent_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    _seed_nodes(cerebrofy_dir)

    _payload(
        _invoke(
            [
                "claim",
                "auth/tokens.py",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    who = _payload(_invoke(["who", "--format", "json"]))
    assert who["active_agents"][0]["intent"] == "claiming 2 neuron(s)"


def test_claim_ttl_zero_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_repo(tmp_path, monkeypatch)

    result = _invoke(
        [
            "claim",
            "n1",
            "--ttl-minutes",
            "0",
            "--agent-id",
            "agent-1",
        ]
    )

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert "--ttl-minutes" in result.output


def test_release_file_path_releases_all_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    _seed_nodes(cerebrofy_dir)

    _payload(
        _invoke(
            [
                "claim",
                "auth/tokens.py",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    released = _payload(
        _invoke(
            [
                "release",
                "auth/tokens.py",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    assert released == {
        "released": [
            "auth/tokens.py::validate_token",
            "auth/tokens.py::refresh_token",
        ]
    }
    who = _payload(_invoke(["who", "--format", "json"]))
    assert who["active_agents"] == []


def test_release_specific_and_all_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_repo(tmp_path, monkeypatch)
    _payload(
        _invoke(
            [
                "claim",
                "n1",
                "n2",
                "--intent",
                "work",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )

    partial = _payload(
        _invoke(
            [
                "release",
                "n1",
                "--agent-id",
                "agent-1",
                "--format",
                "json",
            ]
        )
    )
    assert partial == {"released": ["n1"]}

    remaining = _payload(
        _invoke(["release", "--agent-id", "agent-1", "--format", "json"])
    )
    assert remaining == {"released": ["n2"]}


def test_release_unknown_agent_exits_no_active_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_repo(tmp_path, monkeypatch)

    result = _invoke(
        ["release", "--agent-id", "ghost", "--format", "json"]
    )

    assert result.exit_code == 1
    assert f"Error: [{NO_ACTIVE_AGENT}]" in result.output


def test_conflicts_json_from_memories_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    _seed_memories(cerebrofy_dir)

    payload = _payload(_invoke(["conflicts", "--format", "json"]))

    assert set(payload) == {"memory_conflicts", "overlapping_claims"}
    assert payload["overlapping_claims"] == []
    assert len(payload["memory_conflicts"]) == 1
    assert payload["memory_conflicts"][0]["neuron"] == (
        "auth/tokens.py::validate_token"
    )


def test_resolve_defaults_to_keep_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    old_id, new_id = _seed_memories(cerebrofy_dir)

    # Neither --keep nor --merge: IDEA/docs promise keep_newest by default.
    payload = _payload(
        _invoke(["resolve", old_id, new_id, "--format", "json"])
    )

    assert payload["resolved"] is True
    assert payload["strategy"] == "keep_newest"
    assert payload["winner"] == new_id

    conn = open_memories_db(cerebrofy_dir)
    try:
        assert get_memory(conn, old_id).status == "stale"  # type: ignore[union-attr]
        assert get_memory(conn, new_id).status == "active"  # type: ignore[union-attr]
    finally:
        conn.close()


def test_resolve_same_memory_fails_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    old_id, new_id = _seed_memories(cerebrofy_dir)

    result = _invoke(["resolve", old_id, old_id, "--format", "json"])

    assert result.exit_code == 1
    assert "Error: [CONFIG_ERROR]" in result.output
    assert "itself" in result.output
    conn = open_memories_db(cerebrofy_dir)
    try:
        assert get_memory(conn, old_id).status == "active"  # type: ignore[union-attr]
        assert get_memory(conn, new_id).status == "active"  # type: ignore[union-attr]
    finally:
        conn.close()


def test_resolve_merge_via_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _setup_repo(tmp_path, monkeypatch)
    old_id, new_id = _seed_memories(cerebrofy_dir)

    payload = _payload(
        _invoke(
            [
                "resolve",
                old_id,
                new_id,
                "--merge",
                "--body",
                "Use datetime.now(timezone.utc).",
                "--author",
                "human",
                "--format",
                "json",
            ]
        )
    )

    assert payload["strategy"] == "merge"
    assert payload["superseded"] == [old_id, new_id]
    assert payload["winner"].startswith("mem_")


def test_coordination_group_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_repo(tmp_path, monkeypatch)

    payload = _payload(
        _invoke(["coordination", "who", "--format", "json"])
    )
    assert payload["total_active"] == 0
