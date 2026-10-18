"""Unit tests for cerebrofy.arch.rules — the arch-rules.yaml DSL loader.

Parsing lives in cerebrofy.arch.rules; file loading goes through
cerebrofy.config.loader.load_arch_rules() per the Idea #16 spec.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cerebrofy.arch.rules import (
    AllowedCallersCheck,
    ArchRule,
    MaxBlastRadiusCheck,
    NoCyclesCheck,
    NoEdgeCheck,
    RulesConfig,
    RulesError,
    dump_arch_rules,
    rules_file_exists,
    rules_path,
    scaffold_arch_rules,
)
from cerebrofy.config.loader import load_arch_rules


def _write_rules(root: Path, text: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".cerebrofy").mkdir(exist_ok=True)
    (root / ".cerebrofy" / "arch-rules.yaml").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_arch_rules(tmp_path) is None
    assert not rules_file_exists(tmp_path)


def test_load_full_spec_dsl(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        """
rules:
  - name: no-direct-db-in-api
    description: API controllers must not directly call DB writer functions
    severity: error
    check:
      no_edge:
        from_lobe: api
        to_lobe: db

  - name: no-circular-lobe-deps
    check:
      no_cycles:
        scope: lobes

  - name: embedder-is-isolated
    severity: warning
    check:
      allowed_callers:
        neuron: "*embedder/*"
        from_lobes: [commands, embedder]

  - name: tests-only-call-public-api
    check:
      no_edge:
        from_pattern: "tests/**"
        to_pattern: "*/private/**"

  - name: max-blast-radius
    check:
      max_blast_radius: 50

slack_webhook: "https://hooks.slack.com/services/T/B/X"
""",
    )
    cfg = load_arch_rules(tmp_path)
    assert cfg is not None
    assert cfg.rule_names == (
        "no-direct-db-in-api",
        "no-circular-lobe-deps",
        "embedder-is-isolated",
        "tests-only-call-public-api",
        "max-blast-radius",
    )
    assert cfg.slack_webhook == "https://hooks.slack.com/services/T/B/X"

    r0 = cfg.rules[0]
    assert r0.severity == "error"
    assert r0.description == "API controllers must not directly call DB writer functions"
    assert isinstance(r0.check, NoEdgeCheck)
    assert r0.check == NoEdgeCheck(from_lobe="api", to_lobe="db")

    r1 = cfg.rules[1]
    assert isinstance(r1.check, NoCyclesCheck)
    assert r1.check.scope == "lobes"
    assert r1.severity == "warning"  # default severity

    r2 = cfg.rules[2]
    assert isinstance(r2.check, AllowedCallersCheck)
    assert r2.check.neuron == "*embedder/*"
    assert r2.check.from_lobes == ("commands", "embedder")

    r3 = cfg.rules[3]
    assert isinstance(r3.check, NoEdgeCheck)
    assert r3.check.from_patterns == ("tests/**",)
    assert r3.check.to_patterns == ("*/private/**",)

    r4 = cfg.rules[4]
    assert isinstance(r4.check, MaxBlastRadiusCheck)
    assert r4.check.limit == 50


def test_load_scaffold_yields_zero_rules(tmp_path: Path) -> None:
    path = rules_path(tmp_path)
    scaffold_arch_rules(path)
    cfg = load_arch_rules(tmp_path)
    assert cfg is not None
    assert cfg.rules == ()
    assert cfg.slack_webhook is None


def test_rules_file_exists(tmp_path: Path) -> None:
    path = rules_path(tmp_path)
    scaffold_arch_rules(path)
    assert rules_file_exists(tmp_path)


def test_load_max_blast_radius_dict_form(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        "rules:\n  - name: m\n    check:\n      max_blast_radius:\n        limit: 12\n",
    )
    cfg = load_arch_rules(tmp_path)
    assert cfg is not None
    assert isinstance(cfg.rules[0].check, MaxBlastRadiusCheck)
    assert cfg.rules[0].check.limit == 12


def test_load_no_cycles_bare_scalar_scope(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        "rules:\n  - name: c\n    check:\n      no_cycles: lobes\n",
    )
    cfg = load_arch_rules(tmp_path)
    assert cfg is not None
    assert cfg.rules[0].check == NoCyclesCheck(scope="lobes")


def test_load_pattern_lists(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        """
rules:
  - name: multi
    check:
      no_edge:
        from_pattern: ["a/**", "b/**"]
        to_pattern: ["c/**"]
""",
    )
    cfg = load_arch_rules(tmp_path)
    assert cfg is not None
    check = cfg.rules[0].check
    assert isinstance(check, NoEdgeCheck)
    assert check.from_patterns == ("a/**", "b/**")
    assert check.to_patterns == ("c/**",)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def _expect_rules_error(root: Path, text: str, match: str) -> None:
    _write_rules(root, text)
    with pytest.raises(RulesError, match=match):
        load_arch_rules(root)


def test_error_top_level_not_mapping(tmp_path: Path) -> None:
    _expect_rules_error(tmp_path, "- just\n- a list\n", "top-level YAML mapping")


def test_error_rules_not_list(tmp_path: Path) -> None:
    _expect_rules_error(tmp_path, "rules: not-a-list\n", "'rules' must be a list")


def test_error_rule_not_mapping(tmp_path: Path) -> None:
    _expect_rules_error(tmp_path, "rules:\n  - 42\n", "must be a mapping")


def test_error_missing_name(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - severity: error\n    check:\n      no_cycles: lobes\n",
        "missing required field 'name'",
    )


def test_error_bad_severity(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    severity: fatal\n    check:\n      no_cycles: lobes\n",
        "severity must be one of",
    )


def test_error_missing_check(tmp_path: Path) -> None:
    _expect_rules_error(tmp_path, "rules:\n  - name: x\n", "'check'")


def test_error_unknown_check_type(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      teleport: {}\n",
        "unknown check type 'teleport'",
    )


def test_error_multiple_check_entries(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        """
rules:
  - name: x
    check:
      no_cycles: lobes
      max_blast_radius: 5
""",
        "exactly one entry",
    )


def test_error_no_edge_missing_selectors(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      no_edge:\n        from_lobe: api\n",
        "target selector",
    )


def test_error_no_edge_unknown_key(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      no_edge:\n        from_lobe: api\n        sideways: 1\n",
        "unknown section",
    )


def test_error_no_cycles_bad_scope(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      no_cycles:\n        scope: functions\n",
        "scope='lobes'",
    )


def test_error_allowed_callers_missing_neuron(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      allowed_callers:\n        from_lobes: [api]\n",
        "'neuron'",
    )


def test_error_allowed_callers_missing_lobes(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      allowed_callers:\n        neuron: \"*a/*\"\n",
        "from_lobes",
    )


def test_error_max_blast_radius_not_positive(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      max_blast_radius: 0\n",
        "positive integer",
    )


def test_error_max_blast_radius_bool(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules:\n  - name: x\n    check:\n      max_blast_radius: true\n",
        "positive integer",
    )


def test_error_duplicate_rule_names(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        """
rules:
  - name: dup
    check: { no_cycles: lobes }
  - name: dup
    check: { no_cycles: lobes }
""",
        "duplicate rule name 'dup'",
    )


def test_error_bad_slack_webhook_type(tmp_path: Path) -> None:
    _expect_rules_error(
        tmp_path,
        "rules: []\nslack_webhook: 12345\n",
        "'slack_webhook' must be a webhook URL",
    )


# ---------------------------------------------------------------------------
# Dump / reload round-trip
# ---------------------------------------------------------------------------


def test_dump_round_trip(tmp_path: Path) -> None:
    cfg = RulesConfig(
        rules=(
            ArchRule(
                name="edge",
                severity="error",
                description="no hopscotch",
                check=NoEdgeCheck(from_lobe="api", to_patterns=("priv/**",)),
            ),
            ArchRule(
                name="iso",
                severity="warning",
                check=AllowedCallersCheck(neuron="*embedder/*", from_lobes=("commands",)),
            ),
            ArchRule(name="cyc", severity="error", check=NoCyclesCheck(scope="lobes")),
            ArchRule(name="rad", severity="warning", check=MaxBlastRadiusCheck(limit=9)),
        ),
        slack_webhook="https://hooks.slack.com/services/X",
    )
    path = rules_path(tmp_path)
    dump_arch_rules(cfg, path)
    reloaded = load_arch_rules(tmp_path)
    assert reloaded == cfg


def test_scaffold_content_mentions_rule_types(tmp_path: Path) -> None:
    path = rules_path(tmp_path)
    scaffold_arch_rules(path)
    text = path.read_text(encoding="utf-8")
    for token in ("no_edge", "no_cycles", "allowed_callers", "max_blast_radius", "severity:"):
        assert token in text


def test_rules_yaml_smoke_via_yaml_module(tmp_path: Path) -> None:
    """The DSL sample from the spec parses with plain yaml (no Cerebrofy types)."""
    data = yaml.safe_load(
        """
rules:
  - name: r
    severity: error
    check:
      no_edge:
        from_lobe: api
        to_lobe: db
"""
    )
    assert data["rules"][0]["check"]["no_edge"] == {"from_lobe": "api", "to_lobe": "db"}
