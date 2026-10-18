"""Unit tests for cerebrofy.arch.history — JSONL sidecar I/O and derivations."""

from __future__ import annotations

import json
from pathlib import Path

from cerebrofy.arch.checker import CheckResult, RuleResult, Violation
from cerebrofy.arch.history import (
    HistoryEntry,
    RuleFailure,
    current_commit,
    entry_from_result,
    first_violation_map,
    history_path,
    read_history,
    record_history,
)
from cerebrofy.arch.rules import ArchRule, NoEdgeCheck


def _rule(name: str, severity: str) -> ArchRule:
    return ArchRule(
        name=name, severity=severity, check=NoEdgeCheck(from_lobe="api", to_lobe="db")
    )


def _violation(name: str, file: str = "src/api/views.py") -> Violation:
    return Violation(
        rule_name=name,
        severity="error",
        kind="edge",
        location=f"{file}::f → other.py::g",
        file=file,
        line=1,
        detail="d",
        src_name="f",
        dst_name="g",
    )


def _result(*rule_names: str) -> CheckResult:
    rule_results = []
    for name in rule_names:
        violations: tuple[Violation, ...] = (
            (_violation(name),) if name != "clean" else ()
        )
        rule_results.append(RuleResult(rule=_rule(name, "error"), violations=violations))
    return CheckResult(rule_results=rule_results)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def test_history_round_trip(tmp_path: Path) -> None:
    entry = HistoryEntry(
        ts=1718793600,
        result="FAIL",
        rules_checked=3,
        commit="abc1234",
        since="HEAD~1",
        passing=("clean",),
        failing=(RuleFailure("bad", "error", 2),),
        config_errors=("typo: unknown lobe(s) ap",),
    )
    record_history(tmp_path, entry)
    rows = history_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["result"] == "FAIL"

    assert read_history(tmp_path) == [entry]


def test_record_history_appends(tmp_path: Path) -> None:
    record_history(tmp_path, HistoryEntry(ts=1, result="PASS", rules_checked=1))
    record_history(tmp_path, HistoryEntry(ts=2, result="FAIL", rules_checked=1))
    loaded = read_history(tmp_path)
    assert [e.ts for e in loaded] == [1, 2]


def test_record_history_trims_to_max(tmp_path: Path) -> None:
    for i in range(5):
        record_history(
            tmp_path,
            HistoryEntry(ts=i, result="PASS", rules_checked=1),
            max_entries=3,
        )
    loaded = read_history(tmp_path)
    assert len(loaded) == 3
    assert [e.ts for e in loaded] == [2, 3, 4]


def test_read_history_skips_malformed_lines(tmp_path: Path) -> None:
    path = history_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps(
        {"ts": 1, "result": "PASS", "rules_checked": 0, "passing": [], "failing": [],
         "config_errors": []}
    )
    path.write_text("not json\n{broken\n" + good + "\n", encoding="utf-8")
    loaded = read_history(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].ts == 1


def test_read_history_empty_when_missing(tmp_path: Path) -> None:
    assert read_history(tmp_path) == []


# ---------------------------------------------------------------------------
# entry_from_result
# ---------------------------------------------------------------------------


def test_entry_from_result_maps_violations(tmp_path: Path) -> None:
    entry = entry_from_result(_result("bad", "clean"), "abc1234", None)
    assert entry.result == "FAIL"
    assert entry.rules_checked == 2
    assert entry.failing == (RuleFailure("bad", "error", 1),)
    assert entry.passing == ("clean",)
    assert entry.commit == "abc1234"
    assert entry.config_errors == ()

    record_history(tmp_path, entry)
    assert read_history(tmp_path)[0].failing == entry.failing


def test_entry_includes_config_errors() -> None:
    result = CheckResult(
        rule_results=[
            RuleResult(
                rule=_rule("typo", "error"),
                error="unknown lobe(s) x",
            )
        ]
    )
    entry = entry_from_result(result, None, None)
    assert entry.config_errors == ("'typo': unknown lobe(s) x",)
    assert entry.result == "PASS"


def test_history_payload_names_only() -> None:
    """History payloads never embed source code — names and counts only."""
    payload = json.dumps(entry_from_result(_result("bad"), None, None).to_dict())
    assert "src/api/views.py" not in payload


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------


def test_first_violation_map_picks_earliest() -> None:
    early = HistoryEntry(
        ts=1, result="FAIL", rules_checked=2, failing=(RuleFailure("bad", "error", 1),)
    )
    later = HistoryEntry(
        ts=9, result="FAIL", rules_checked=2, failing=(RuleFailure("bad", "error", 3),)
    )
    firsts = first_violation_map([early, later])
    assert firsts["bad"] is early

    other = HistoryEntry(
        ts=5, result="FAIL", rules_checked=1, failing=(RuleFailure("other", "warning", 1),)
    )
    firsts = first_violation_map([early, other, later])
    assert firsts["other"] is other


def test_current_commit_outside_git(tmp_path: Path) -> None:
    assert current_commit(tmp_path) is None
