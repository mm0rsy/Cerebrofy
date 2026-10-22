"""Unit tests for memory conflict resolution strategies (Idea #25)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrofy.coordination.resolver import ConflictResolver
from cerebrofy.memory.store import Memory, get_memory, open_memories_db, write_memory

ZERO_EMBEDDING = [0.0] * 384


def _seed(
    tmp_path: Path,
    memories: list[tuple[str, int, str]],
) -> Path:
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True, exist_ok=True)
    conn = open_memories_db(cerebrofy_dir)
    try:
        for memory_id, created_ts, author in memories:
            write_memory(
                conn,
                Memory(
                    id=memory_id,
                    neuron_id="auth/tokens.py::validate_token",
                    lobe="auth",
                    type="warning",
                    title=f"title-{memory_id}",
                    body=f"body from {author}",
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
    return cerebrofy_dir


def _status(cerebrofy_dir: Path, memory_id: str) -> str | None:
    conn = open_memories_db(cerebrofy_dir)
    try:
        memory = get_memory(conn, memory_id)
        return memory.status if memory is not None else None
    finally:
        conn.close()


def test_keep_newest_marks_older_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _seed(
        tmp_path, [("mem_old", 1000, "alice"), ("mem_new", 2000, "bob")]
    )

    result = ConflictResolver(cerebrofy_dir).resolve_pair("mem_old", "mem_new", "newest")

    assert result["resolved"] is True
    assert result["strategy"] == "keep_newest"
    assert result["winner"] == "mem_new"
    assert result["loser"] == "mem_old"
    assert _status(cerebrofy_dir, "mem_old") == "stale"
    assert _status(cerebrofy_dir, "mem_new") == "active"


def test_keep_newest_tie_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _seed(
        tmp_path, [("mem_a", 2000, "alice"), ("mem_b", 2000, "bob")]
    )

    result = ConflictResolver(cerebrofy_dir).resolve_pair("mem_a", "mem_b", "keep_newest")

    # Equal timestamps: the lexicographically higher id wins.
    assert result["winner"] == "mem_b"
    assert result["loser"] == "mem_a"


def test_keep_by_author_requires_author_and_keeps_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _seed(
        tmp_path, [("mem_alice", 1000, "alice"), ("mem_bob", 2000, "bob")]
    )
    resolver = ConflictResolver(cerebrofy_dir)

    with pytest.raises(ValueError):
        resolver.resolve_pair("mem_alice", "mem_bob", "keep_by_author")

    with pytest.raises(ValueError):
        resolver.resolve_pair(
            "mem_alice", "mem_bob", "keep_by_author", author="nobody"
        )

    result = resolver.resolve_pair(
        "mem_alice", "mem_bob", "keep_by_author", author="alice"
    )
    assert result["winner"] == "mem_alice"
    assert _status(cerebrofy_dir, "mem_alice") == "active"
    assert _status(cerebrofy_dir, "mem_bob") == "stale"


def test_human_review_mutates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _seed(
        tmp_path, [("mem_a", 1000, "alice"), ("mem_b", 2000, "bob")]
    )

    result = ConflictResolver(cerebrofy_dir).resolve_pair(
        "mem_a", "mem_b", "human_review"
    )

    assert result["resolved"] is False
    assert result["requires_review"] is True
    assert result["strategy"] == "human_review"
    assert result["resolution_options"] == [
        "keep_newest",
        "keep_by_author",
        "human_review",
        "merge",
    ]
    assert _status(cerebrofy_dir, "mem_a") == "active"
    assert _status(cerebrofy_dir, "mem_b") == "active"


def test_merge_creates_memory_and_stales_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_embed(title: str, body: str) -> list[float]:
        calls.append((title, body))
        return ZERO_EMBEDDING

    monkeypatch.setattr("cerebrofy.memory.embedder.embed_memory", fake_embed)
    cerebrofy_dir = _seed(
        tmp_path, [("mem_a", 1000, "alice"), ("mem_b", 2000, "bob")]
    )

    result = ConflictResolver(cerebrofy_dir).resolve_pair(
        "mem_a",
        "mem_b",
        "merge",
        author="resolver",
        merged_body="Use datetime.now(timezone.utc) for timestamps.",
    )

    assert result["resolved"] is True
    assert result["strategy"] == "merge"
    assert result["superseded"] == ["mem_a", "mem_b"]
    assert calls and calls[0][1] == "Use datetime.now(timezone.utc) for timestamps."

    merged_id = result["winner"]
    assert merged_id.startswith("mem_")
    assert _status(cerebrofy_dir, "mem_a") == "stale"
    assert _status(cerebrofy_dir, "mem_b") == "stale"

    conn = open_memories_db(cerebrofy_dir)
    try:
        merged = get_memory(conn, merged_id)
    finally:
        conn.close()

    assert merged is not None
    assert merged.body == "Use datetime.now(timezone.utc) for timestamps."
    assert merged.title == "Merged: title-mem_a"
    assert merged.author == "resolver"
    assert merged.status == "active"
    assert merged.tags == ("merged",)


def test_merge_requires_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _seed(
        tmp_path, [("mem_a", 1000, "alice"), ("mem_b", 2000, "bob")]
    )

    with pytest.raises(ValueError) as excinfo:
        ConflictResolver(cerebrofy_dir).resolve_pair("mem_a", "mem_b", "merge")
    # The resolver is shared with the MCP surface, so the message must not
    # reference the CLI-only ``--body`` flag.
    assert "--body" not in str(excinfo.value)
    assert _status(cerebrofy_dir, "mem_a") == "active"
    assert _status(cerebrofy_dir, "mem_b") == "active"


def test_missing_memory_raises_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _seed(tmp_path, [("mem_a", 1000, "alice")])

    resolver = ConflictResolver(cerebrofy_dir)
    with pytest.raises(ValueError):
        resolver.resolve_pair("mem_a", "missing", "newest")
    with pytest.raises(ValueError):
        resolver.resolve_pair("missing", "mem_a", "newest")


def test_resolving_memory_against_itself_raises_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cerebrofy.memory.embedder.embed_memory",
        lambda title, body: ZERO_EMBEDDING,
    )
    cerebrofy_dir = _seed(
        tmp_path, [("mem_a", 1000, "alice"), ("mem_b", 2000, "bob")]
    )
    resolver = ConflictResolver(cerebrofy_dir)

    with pytest.raises(ValueError, match="itself"):
        resolver.resolve_pair("mem_a", "mem_a", "newest")

    assert _status(cerebrofy_dir, "mem_a") == "active"
    assert _status(cerebrofy_dir, "mem_b") == "active"
