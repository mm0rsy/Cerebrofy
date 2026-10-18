"""Unit tests for cerebrofy.arch.reporter — text / markdown / json / annotations."""

from __future__ import annotations

import json

from cerebrofy.arch.checker import CheckResult, RuleResult, Violation
from cerebrofy.arch.reporter import (
    _json_dict,
    render_annotations,
    render_json,
    render_markdown,
    render_text,
)
from cerebrofy.arch.rules import ArchRule, NoEdgeCheck


def _rule(name: str, severity: str) -> ArchRule:
    return ArchRule(
        name=name, severity=severity, check=NoEdgeCheck(from_lobe="api", to_lobe="db")
    )


def _violation(
    name: str,
    severity: str,
    *,
    kind: str = "edge",
    location: str = "src/api/views.py::endpoint → src/db/writer.py::write",
    detail: str = "api → db",
    introduced: str | None = None,
    line: int = 7,
    dst_name: str | None = "write",
    file: str = "src/api/views.py",
) -> Violation:
    return Violation(
        rule_name=name,
        severity=severity,
        kind=kind,
        location=location,
        file=file,
        line=line,
        detail=detail,
        src_name="endpoint",
        dst_name=dst_name,
        introduced_in=introduced,
    )


def _fail_result() -> CheckResult:
    return CheckResult(
        rule_results=[
            RuleResult(rule=_rule("no-db", "error"), violations=(_violation("no-db", "error"),))
        ]
    )


def _warn_result() -> CheckResult:
    return CheckResult(
        rule_results=[
            RuleResult(
                rule=_rule("radius", "warning"),
                violations=(
                    _violation(
                        "radius",
                        "warning",
                        kind="blast_radius",
                        location="src/graph/resolver.py::resolve",
                        detail="blast_radius=67 (limit: 50)",
                        dst_name=None,
                        file="src/graph/resolver.py",
                    ),
                ),
            )
        ]
    )


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------


def test_text_fail_report() -> None:
    result = _fail_result()
    result.rule_results.append(RuleResult(rule=_rule("clean", "warning")))
    text = render_text(result)
    assert "🧠 Cerebrofy Architecture Check" in text
    assert "Rules Checked: 2" in text
    assert "✅ Passing: 1" in text
    assert "🔴 Failing: 1" in text
    assert "🔴 RULE VIOLATION: no-db" in text
    assert "src/api/views.py::endpoint → src/db/writer.py::write" in text
    assert "Fix: desc-fix-here" not in text  # no description set → kind fallback
    assert "RESULT: ❌ FAILED (1 error) — commit blocked" in text


def test_text_introduced_in_and_fix_description() -> None:
    rule = ArchRule(
        name="no-db",
        severity="error",
        check=NoEdgeCheck(from_lobe="api", to_lobe="db"),
        description="Route through a service layer.",
    )
    result = CheckResult(
        rule_results=[
            RuleResult(
                rule=rule,
                violations=(
                    _violation("no-db", "error", introduced="commit abc1234 by a@b (2 hours ago)"),
                ),
            )
        ]
    )
    text = render_text(result)
    assert "Introduced in: commit abc1234 by a@b (2 hours ago)" in text
    assert "Fix: Route through a service layer." in text


def test_text_pass() -> None:
    result = CheckResult(rule_results=[RuleResult(rule=_rule("clean", "error"))])
    text = render_text(result)
    assert "RESULT: ✅ PASSED (all rules clear)" in text


def test_text_warn() -> None:
    text = render_text(_warn_result())
    assert "⚠️  WARNING: radius" in text
    assert "blast_radius=67 (limit: 50)" in text
    assert "RESULT: ⚠️  WARN (1 warning)" in text
    assert "commit blocked" not in text


def test_text_config_errors_line() -> None:
    result = CheckResult(
        rule_results=[RuleResult(rule=_rule("typo", "error"), error="unknown lobe(s) ap")]
    )
    text = render_text(result)
    assert "⛔ Config: rule 'typo' — unknown lobe(s) ap" in text


def test_text_hook_mode_quiet_when_clean() -> None:
    result = CheckResult(rule_results=[RuleResult(rule=_rule("clean", "error"))])
    assert render_text(result, hook_mode=True) == ""


def test_text_hook_mode_keeps_violations_and_verdict() -> None:
    text = render_text(_fail_result(), hook_mode=True)
    assert "🧠" not in text
    assert "Rules Checked" not in text
    assert "🔴 RULE VIOLATION: no-db" in text
    assert "RESULT: ❌ FAILED (1 error)" in text
    assert "commit blocked" not in text


def test_text_hook_mode_shows_warnings_without_verdict() -> None:
    text = render_text(_warn_result(), hook_mode=True)
    assert "🧠" not in text
    assert "RESULT" not in text
    assert "⚠️  WARNING: radius" in text
    assert "blast_radius=67 (limit: 50)" in text


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------


def test_markdown_fail() -> None:
    md = render_markdown(_fail_result())
    assert md.startswith("## 🧠 Cerebrofy Architecture Check")
    assert "**Result: ❌ FAIL**" in md
    assert "### 🔴 no-db (error)" in md
    assert "`src/api/views.py::endpoint → src/db/writer.py::write`" in md


def test_markdown_pass() -> None:
    result = CheckResult(rule_results=[RuleResult(rule=_rule("clean", "error"))])
    md = render_markdown(result)
    assert "**Result: ✅ PASS**" in md
    assert "No architecture violations detected." in md


def test_markdown_config_error_note() -> None:
    result = CheckResult(
        rule_results=[RuleResult(rule=_rule("typo", "error"), error="unknown lobe(s) ap")]
    )
    md = render_markdown(result)
    assert "⛔ **typo** skipped — unknown lobe(s) ap" in md


# ---------------------------------------------------------------------------
# json (spec schema)
# ---------------------------------------------------------------------------


def test_json_spec_schema() -> None:
    result = _fail_result()
    result.rule_results.append(RuleResult(rule=_rule("warn-rule", "warning")))
    result.rule_results.append(RuleResult(rule=_rule("cfg", "error"), error="bad lobe"))

    data = json.loads(render_json(result))
    assert data["rules_checked"] == 3
    assert data["passing"] == ["warn-rule"]
    assert data["result"] == "FAIL"
    assert data["failing"] == [
        {
            "rule": "no-db",
            "severity": "error",
            "violations": [
                {
                    "from_neuron": "endpoint",
                    "to_neuron": "write",
                    "file": "src/api/views.py",
                    "line": 7,
                }
            ],
        }
    ]
    assert {"rule": "warn-rule-warnish"} not in data["warnings"]
    assert {"rule": "cfg", "message": "bad lobe"} in data["warnings"]


def test_json_warning_violations_are_messages() -> None:
    data = json.loads(render_json(_warn_result()))
    assert data["result"] == "WARN"
    assert data["passing"] == []
    assert data["failing"] == []
    assert data["warnings"] == [
        {
            "rule": "radius",
            "message": "src/graph/resolver.py::resolve — blast_radius=67 (limit: 50)",
        }
    ]


def test_json_dict_passing_only() -> None:
    result = CheckResult(rule_results=[RuleResult(rule=_rule("ok", "error"))])
    data = _json_dict(result)
    assert data == {
        "rules_checked": 1,
        "passing": ["ok"],
        "failing": [],
        "warnings": [],
        "result": "PASS",
    }


# ---------------------------------------------------------------------------
# github-annotations
# ---------------------------------------------------------------------------


def test_annotations_error_line() -> None:
    text = render_annotations(_fail_result())
    assert text.startswith("::error file=src/api/views.py,line=7::[no-db] ")
    assert "src/api/views.py::endpoint" in text


def test_annotations_warning_line() -> None:
    text = render_annotations(_warn_result())
    assert text.startswith("::warning file=src/graph/resolver.py,line=7::[radius] ")


def test_annotations_empty_when_pass() -> None:
    result = CheckResult(rule_results=[RuleResult(rule=_rule("ok", "error"))])
    assert render_annotations(result) == ""


def test_annotations_truncate_long_messages() -> None:
    v = _violation("r", "error", detail="x" * 1000)
    result = CheckResult(rule_results=[RuleResult(rule=_rule("r", "error"), violations=(v,))])
    line = render_annotations(result)
    assert len(line[line.index("::", 2) + 2 :]) <= 400


def test_blast_radius_violation_uses_kind_fallback_fix() -> None:
    """max_blast_radius violations fall back to the blast_radius fix hint."""
    text = render_text(_warn_result())
    assert "Fix: Consider splitting this function into smaller components." in text
