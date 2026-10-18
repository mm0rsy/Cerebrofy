"""Unit tests for cerebrofy.arch.memory — violation → warning memories (Idea #05)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from cerebrofy.arch.checker import CheckResult, RuleResult, Violation
from cerebrofy.arch.memory import write_violation_memories
from cerebrofy.arch.rules import ArchRule, NoEdgeCheck, NoCyclesCheck


def _rule(name: str, severity: str = "error") -> ArchRule:
    return ArchRule(
        name=name,
        severity=severity,
        check=NoEdgeCheck(from_lobe="a", to_lobe="b"),
        description="Keep a out of b.",
    )


def _violation(
    rule_name: str,
    *,
    file: str,
    location: str,
    severity: str = "error",
) -> Violation:
    return Violation(
        rule_name=rule_name,
        severity=severity,
        kind="edge",
        location=location,
        file=file,
        line=3,
        detail="a → b",
        src_name="f",
        dst_name="g",
    )


def _result_with(errors: int = 1, warnings: int = 0) -> CheckResult:
    rule_results = []
    if errors:
        rule_results.append(
            RuleResult(
                rule=_rule("err-rule"),
                violations=tuple(
                    _violation(
                        "err-rule",
                        file="src/module.py",
                        location=f"src/module.py::caller{i} → src/db.py::write",
                    )
                    for i in range(errors)
                ),
            )
        )
    if warnings:
        rule_results.append(
            RuleResult(
                rule=_rule("warn-rule", severity="warning"),
                violations=tuple(
                    _violation(
                        "warn-rule",
                        file="elsewhere/x.py",
                        location=f"elsewhere/x.py::w{i} → src/db.py::write",
                        severity="warning",
                    )
                    for i in range(warnings)
                ),
            )
        )
    return CheckResult(rule_results=rule_results)


def _write_index_db(cerebrofy_dir: Path, rows: list[tuple[str, str, str]]) -> None:
    db_dir = cerebrofy_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "cerebrofy.db")
    conn.execute("CREATE TABLE nodes (id TEXT, file TEXT, name TEXT)")
    conn.executemany("INSERT INTO nodes VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _patch_store() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Patch memory store/embedder; returns (open_mock, write_mock, conn)."""
    conn = MagicMock()
    conn.execute.return_value = []  # no existing warning titles
    open_mock = MagicMock(return_value=conn)
    write_mock = MagicMock()
    return open_mock, write_mock, conn


def test_writes_error_before_warning_with_spec_fields(tmp_path: Path) -> None:
    _write_index_db(tmp_path, [("n1", "src/module.py", "f")])
    open_mock, write_mock, conn = _patch_store()

    with patch("cerebrofy.memory.store.open_memories_db", open_mock), patch(
        "cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384
    ), patch("cerebrofy.memory.store.write_memory", write_mock):
        written = write_violation_memories(
            _result_with(errors=1, warnings=1), tmp_path, {"src": "src/"}
        )

    assert written == 2
    assert write_mock.call_count == 2

    first = write_mock.call_args_list[0][0][1]  # (conn, memory, vector)
    assert first.type == "warning"
    assert first.title == (
        "Architecture rule 'err-rule' violated at src/module.py::caller0 → src/db.py::write"
    )
    assert "don't repeat it" in first.body
    assert "Fix: Keep a out of b." in first.body  # rule description preferred
    assert first.author == "agent:arch-check"
    assert first.tags == ("arch", "err-rule")
    assert first.decay_score == 1.0
    assert first.status == "active"
    assert first.lobe == "src"
    assert first.neuron_id == "n1"  # resolved from the index DB

    second = write_mock.call_args_list[1][0][1]
    assert second.title.startswith("Architecture rule 'warn-rule'")
    assert second.neuron_id is None  # file not in the index DB
    assert second.lobe == "__unknown__"  # outside configured lobes


def test_no_violations_returns_zero_without_store_access(tmp_path: Path) -> None:
    open_mock = MagicMock()
    with patch("cerebrofy.memory.store.open_memories_db", open_mock):
        assert write_violation_memories(CheckResult(), tmp_path, {}) == 0
    open_mock.assert_not_called()


def test_dedupes_titles_already_in_store(tmp_path: Path) -> None:
    _, write_mock, conn = _patch_store()
    conn.execute.return_value = [
        ("Architecture rule 'err-rule' violated at src/module.py::caller0 → src/db.py::write",),
    ]

    with patch("cerebrofy.memory.store.open_memories_db", return_value=conn), patch(
        "cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384
    ), patch("cerebrofy.memory.store.write_memory", write_mock):
        written = write_violation_memories(_result_with(errors=1), tmp_path, {})

    assert written == 0
    write_mock.assert_not_called()


def test_caps_new_memories_per_run(tmp_path: Path) -> None:
    _, write_mock, conn = _patch_store()
    with patch("cerebrofy.memory.store.open_memories_db", return_value=conn), patch(
        "cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384
    ), patch("cerebrofy.memory.store.write_memory", write_mock):
        written = write_violation_memories(_result_with(errors=12), tmp_path, {})

    assert written == 10  # default cap
    assert write_mock.call_count == 10


def test_respects_explicit_limit(tmp_path: Path) -> None:
    _, write_mock, conn = _patch_store()
    with patch("cerebrofy.memory.store.open_memories_db", return_value=conn), patch(
        "cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384
    ), patch("cerebrofy.memory.store.write_memory", write_mock):
        written = write_violation_memories(_result_with(errors=5, warnings=5), tmp_path, {}, limit=3)

    assert written == 3


def test_cycle_violation_without_file_is_safe(tmp_path: Path) -> None:
    cycle_rule = ArchRule(name="c", severity="error", check=NoCyclesCheck(scope="lobes"))
    violation = Violation(
        rule_name="c",
        severity="error",
        kind="cycle",
        location="api → db → api",
        file="",
        line=0,
        detail="cycle across 2 lobes",
    )
    result = CheckResult(rule_results=[RuleResult(rule=cycle_rule, violations=(violation,))])
    _, write_mock, conn = _patch_store()

    with patch("cerebrofy.memory.store.open_memories_db", return_value=conn), patch(
        "cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384
    ), patch("cerebrofy.memory.store.write_memory", write_mock):
        written = write_violation_memories(result, tmp_path, {})

    assert written == 1
    mem = write_mock.call_args_list[0][0][1]
    assert mem.neuron_id is None
    expected = "Architecture rule 'c' violated at api → db → api"
    assert mem.title == expected
    # cycle fix-hint fallback is used when the description is empty
    assert "cycle" in mem.body.lower()


def test_store_failure_is_swallowed(tmp_path: Path) -> None:
    with patch(
        "cerebrofy.memory.store.open_memories_db", side_effect=RuntimeError("db error")
    ):
        # must not raise
        assert write_violation_memories(_result_with(errors=1), tmp_path, {}) == 0


def test_embedder_failure_is_swallowed(tmp_path: Path) -> None:
    _, write_mock, conn = _patch_store()
    with patch("cerebrofy.memory.store.open_memories_db", return_value=conn), patch(
        "cerebrofy.memory.embedder.embed_memory", side_effect=RuntimeError("no model")
    ), patch("cerebrofy.memory.store.write_memory", write_mock):
        assert write_violation_memories(_result_with(errors=1), tmp_path, {}) == 0