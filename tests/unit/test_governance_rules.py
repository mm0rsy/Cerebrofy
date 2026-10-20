"""Unit tests for the governance rule DSL and evaluator (Idea #18)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrofy.arch.rules import RulesError, dump_arch_rules
from cerebrofy.config.loader import load_arch_rules
from cerebrofy.db.schema import EDGES_DDL, NODES_DDL
from cerebrofy.governance.ownership import AuthorShare, LobeOwnership
from cerebrofy.governance.reviewer import ChangeSet, NewNeuron
from cerebrofy.governance.rules import (
    GovernanceRulesConfig,
    IfBlastRadius,
    IfBusFactor,
    IfNewNeurons,
    evaluate_governance_rules,
    parse_governance_config,
)

_RULES_YAML = """
rules: []
governance:
  rules:
    - name: high-blast-requires-two-reviews
      description: high blast radius needs two approvals
      check:
        if_blast_radius: { gt: 3 }
        then_require_approvals: 2
    - name: silo-lobes-require-backup
      check:
        if_bus_factor: { eq: 1 }
        then_require_non_owner_review: true
    - name: new-neurons-require-coverage
      check:
        if_new_neurons: true
        then_require_test_file: true
"""


def _write_rules(root: Path, text: str) -> None:
    (root / ".cerebrofy").mkdir(parents=True, exist_ok=True)
    (root / ".cerebrofy" / "arch-rules.yaml").write_text(text, encoding="utf-8")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(NODES_DDL)
    conn.execute(EDGES_DDL)
    conn.execute(
        "INSERT INTO nodes (id, name, file, type, line_start, line_end) "
        "VALUES ('auth/a.py::a', 'a', 'auth/a.py', 'function', 1, 2)"
    )
    for index in range(4):
        conn.execute(
            "INSERT INTO nodes (id, name, file, type, line_start, line_end) "
            "VALUES (?, ?, 'api/b.py', 'function', ?, ?)",
            (f"api/b.py::b{index}", f"b{index}", index + 1, index + 1),
        )
        conn.execute(
            "INSERT INTO edges (src_id, dst_id, rel_type) VALUES (?, ?, 'EXTERNAL_CALL')",
            (f"api/b.py::b{index}", "auth/a.py::a"),
        )
    return conn


def _ownership(bus_factor: int = 1) -> dict[str, LobeOwnership]:
    shares = tuple(
        AuthorShare(author=f"dev{index}@example.com", lines=10, score=1.0, share=1.0 / bus_factor)
        for index in range(bus_factor)
    )
    return {
        "auth": LobeOwnership(
            lobe="auth", strategy="explicit", authors=shares, total_lines=10
        )
    }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_load_governance_rules_from_arch_rules(tmp_path: Path) -> None:
    _write_rules(tmp_path, _RULES_YAML)
    rules = load_arch_rules(tmp_path)
    assert rules is not None
    assert rules.governance is not None
    assert rules.governance.rule_names == (
        "high-blast-requires-two-reviews",
        "silo-lobes-require-backup",
        "new-neurons-require-coverage",
    )
    assert isinstance(rules.governance.rules[0].condition, IfBlastRadius)
    assert rules.governance.rules[0].condition.gt == 3
    assert rules.governance.rules[0].require_approvals == 2
    assert isinstance(rules.governance.rules[1].condition, IfBusFactor)
    assert isinstance(rules.governance.rules[2].condition, IfNewNeurons)


def test_governance_absent_is_none(tmp_path: Path) -> None:
    _write_rules(tmp_path, "rules: []\n")
    rules = load_arch_rules(tmp_path)
    assert rules is not None
    assert rules.governance is None


def test_parse_governance_rejects_missing_condition(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one if_"):
        parse_governance_config(
            {"rules": [{"name": "x", "check": {"then_require_approvals": 2}}]},
            tmp_path,
        )


def test_parse_governance_rejects_multiple_conditions(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one if_"):
        parse_governance_config(
            {
                "rules": [
                    {
                        "name": "x",
                        "check": {
                            "if_blast_radius": {"gt": 1},
                            "if_bus_factor": {"eq": 1},
                            "then_require_test_file": True,
                        },
                    }
                ]
            },
            tmp_path,
        )


def test_parse_governance_rejects_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown governance check key"):
        parse_governance_config(
            {
                "rules": [
                    {
                        "name": "x",
                        "check": {"if_bus_factor": {"eq": 1}, "then_teleport": True},
                    }
                ]
            },
            tmp_path,
        )


def test_parse_governance_rejects_bad_threshold(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        parse_governance_config(
            {
                "rules": [
                    {
                        "name": "x",
                        "check": {"if_blast_radius": {"gt": -1}, "then_require_approvals": 1},
                    }
                ]
            },
            tmp_path,
        )


def test_arch_rules_malformed_governance_becomes_rules_error(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        "rules: []\ngovernance:\n  rules:\n    - name: x\n      check:\n"
        "        then_require_test_file: true\n",
    )
    with pytest.raises(RulesError, match="exactly one if_"):
        load_arch_rules(tmp_path)


def test_dump_arch_rules_preserves_governance(tmp_path: Path) -> None:
    _write_rules(tmp_path, _RULES_YAML)
    rules = load_arch_rules(tmp_path)
    assert rules is not None
    dump_arch_rules(rules, tmp_path / "out.yaml")
    reloaded = load_arch_rules(tmp_path)
    assert reloaded is not None
    dumped = (tmp_path / "out.yaml").read_text(encoding="utf-8")
    assert "governance:" in dumped
    assert "then_require_approvals: 2" in dumped
    assert reloaded.governance is not None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _evaluate(
    tmp_path: Path,
    yaml_text: str,
    *,
    changes: ChangeSet | None = None,
    ownership: dict[str, LobeOwnership] | None = None,
) -> object:
    _write_rules(tmp_path, yaml_text)
    rules = load_arch_rules(tmp_path)
    assert rules is not None and rules.governance is not None
    conn = _db()
    try:
        return evaluate_governance_rules(
            rules.governance,
            conn,
            tmp_path,
            {"auth": "auth", "api": "api"},
            changes=changes,
            ownership=ownership if ownership is not None else _ownership(),
        )
    finally:
        conn.close()


def test_rule_not_triggered_passes(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: huge-only
      check:
        if_blast_radius: { gt: 100 }
        then_require_approvals: 2
"""
    result = _evaluate(tmp_path, yaml_text, changes=ChangeSet("diff", files=("auth/a.py",)))
    assert result.result == "PASS"
    assert result.evaluations[0].triggered is False


def test_blast_radius_rule_fails_without_approvals(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: high-blast
      check:
        if_blast_radius: { gt: 3 }
        then_require_approvals: 2
"""
    changes = ChangeSet("pr", files=("auth/a.py",), approvals=1)
    result = _evaluate(tmp_path, yaml_text, changes=changes)
    assert result.result == "FAIL"
    assert "1 approval(s); 2 required" in result.failing[0].reason


def test_blast_radius_rule_passes_with_approvals(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: high-blast
      check:
        if_blast_radius: { gt: 3 }
        then_require_approvals: 2
"""
    changes = ChangeSet("pr", files=("auth/a.py",), approvals=2)
    result = _evaluate(tmp_path, yaml_text, changes=changes)
    assert result.result == "PASS"


def test_blast_radius_rule_warns_without_pr_metadata(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: high-blast
      check:
        if_blast_radius: { gt: 3 }
        then_require_approvals: 2
"""
    changes = ChangeSet("diff", files=("auth/a.py",))
    result = _evaluate(tmp_path, yaml_text, changes=changes)
    assert result.result == "WARN"
    assert "no PR metadata" in result.warnings[0].reason


def test_bus_factor_rule_requires_non_owner(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: silo
      check:
        if_bus_factor: { eq: 1 }
        then_require_non_owner_review: true
"""
    owner_changes = ChangeSet("pr", files=("auth/a.py",), reviewers=("dev0",))
    result = _evaluate(
        tmp_path, yaml_text, changes=owner_changes, ownership=_ownership(1)
    )
    assert result.result == "FAIL"

    non_owner = ChangeSet("pr", files=("auth/a.py",), reviewers=("stranger",))
    result = _evaluate(tmp_path, yaml_text, changes=non_owner, ownership=_ownership(1))
    assert result.result == "PASS"


def test_bus_factor_rule_warns_without_reviews(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: silo
      check:
        if_bus_factor: { eq: 1 }
        then_require_non_owner_review: true
"""
    result = _evaluate(
        tmp_path,
        yaml_text,
        changes=ChangeSet("diff", files=("auth/a.py",)),
        ownership=_ownership(1),
    )
    assert result.result == "WARN"


def test_new_neurons_require_test_file(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: coverage
      check:
        if_new_neurons: true
        then_require_test_file: true
"""
    new = (NewNeuron(id="auth/a.py::new", name="new", file="auth/a.py"),)
    failing = ChangeSet("diff", files=("auth/a.py",), new_neurons=new)
    result = _evaluate(tmp_path, yaml_text, changes=failing)
    assert result.result == "FAIL"

    passing = ChangeSet(
        "diff", files=("auth/a.py", "tests/test_a.py"), new_neurons=new
    )
    result = _evaluate(tmp_path, yaml_text, changes=passing)
    assert result.result == "PASS"


def test_result_aggregates_fail_over_warn(tmp_path: Path) -> None:
    yaml_text = """
rules: []
governance:
  rules:
    - name: warned
      check:
        if_bus_factor: { eq: 1 }
        then_require_non_owner_review: true
    - name: failed
      check:
        if_blast_radius: { gt: 0 }
        then_require_test_file: true
"""
    result = _evaluate(
        tmp_path,
        yaml_text,
        changes=ChangeSet("diff", files=("auth/a.py",)),
        ownership=_ownership(1),
    )
    assert result.result == "FAIL"
    assert result.rules_checked == 2
    assert len(result.failing) == 1
    assert len(result.warnings) == 1
    payload = result.to_dict()
    assert payload["result"] == "FAIL"
    assert payload["rules_checked"] == 2
    assert len(payload["failing"]) == 1


def test_governance_rules_config_rule_names() -> None:
    config = GovernanceRulesConfig()
    assert config.rule_names == ()
