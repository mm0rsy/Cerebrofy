"""Unit tests for review findings, severity scoring, and report rendering."""

from __future__ import annotations

import json

from cerebrofy.review.finding import (
    Finding,
    HealthDelta,
    ReviewReport,
    SuggestedReviewer,
    compute_severity_score,
    filter_findings,
    format_inline_comment,
    format_summary,
    sort_findings,
)


def _finding(
    *,
    check_type: str = "blast_radius",
    neuron: str = "validate_token",
    file: str = "auth/tokens.py",
    line: int = 10,
    severity: str = "warning",
    message: str = "message",
    suggestion: str = "suggestion",
    score: float = 0.0,
) -> Finding:
    return Finding(
        check_type=check_type,
        neuron=neuron,
        file=file,
        line=line,
        severity=severity,
        message=message,
        suggestion=suggestion,
        severity_score=score,
    )


# ---------------------------------------------------------------------------
# Severity formula
# ---------------------------------------------------------------------------


def test_severity_formula_base_only() -> None:
    assert compute_severity_score("error") == 9.0
    assert compute_severity_score("warning") == 6.0
    assert compute_severity_score("info") == 3.0


def test_severity_blast_factor() -> None:
    # base * (1 + blast/50 + 1 + 1)
    assert compute_severity_score("error", 50) == 12.0
    assert compute_severity_score("error", 25) == 10.5
    assert compute_severity_score("error", -5) == 9.0


def test_severity_memory_and_coverage_factors() -> None:
    assert compute_severity_score("error", has_memory_warning=True) == 10.5
    assert compute_severity_score("error", uncovered=True) == 9.9
    assert (
        compute_severity_score(
            "warning", 10, has_memory_warning=True, uncovered=True
        )
        == 8.0
    )


def test_severity_unknown_falls_back_to_info() -> None:
    assert compute_severity_score("critical") == 3.0


def test_finding_autocomputes_score() -> None:
    finding = _finding(severity="error")
    assert finding.severity_score == 9.0


def test_finding_keeps_explicit_score() -> None:
    assert _finding(score=42.5).severity_score == 42.5


def test_finding_icons() -> None:
    assert _finding(severity="error").severity_icon == "🔴"
    assert _finding(severity="warning").severity_icon == "🟡"
    assert _finding(severity="info").severity_icon == "🔵"
    assert _finding(severity="other").severity_icon == "⚪"
    assert _finding(check_type="arch_rule").check_icon == "🏛️"
    assert _finding(check_type="unknown").check_icon == "•"


def test_finding_to_dict_is_spec_shaped() -> None:
    payload = _finding(severity="error").to_dict()
    assert set(payload) == {
        "check_type",
        "neuron",
        "file",
        "line",
        "severity",
        "message",
        "suggestion",
        "severity_score",
    }
    assert payload["neuron"] == "validate_token"
    assert payload["severity_score"] == 9.0


# ---------------------------------------------------------------------------
# Filtering and ordering
# ---------------------------------------------------------------------------


def test_filter_findings_all_and_thresholds() -> None:
    error = _finding(severity="error", neuron="a")
    warning = _finding(severity="warning", neuron="b")
    info = _finding(severity="info", neuron="c")
    findings = [info, error, warning]

    assert filter_findings(findings, "all") == [info, error, warning]
    assert filter_findings(findings, "warning") == [error, warning]
    assert filter_findings(findings, "error") == [error]
    assert filter_findings(findings, "unknown") == findings


def test_sort_findings_orders_by_score_then_severity() -> None:
    low = _finding(neuron="low", severity="info", score=3.0)
    high = _finding(neuron="high", severity="error", score=9.0)
    warning = _finding(neuron="warning", severity="warning", score=6.0)
    tied_error = _finding(neuron="tied", severity="error", score=6.0)

    ordered = sort_findings([low, tied_error, warning, high])
    assert [finding.neuron for finding in ordered] == [
        "high",
        "tied",
        "warning",
        "low",
    ]


def test_sort_findings_tie_breaks_by_file_and_line() -> None:
    a = _finding(neuron="a", file="z.py", line=1, score=5.0)
    b = _finding(neuron="b", file="a.py", line=9, score=5.0)
    c = _finding(neuron="c", file="a.py", line=2, score=5.0)

    assert [finding.neuron for finding in sort_findings([a, b, c])] == ["c", "b", "a"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_format_inline_comment() -> None:
    body = format_inline_comment(
        _finding(
            check_type="arch_rule",
            severity="error",
            message="Auth must not call billing",
            suggestion="Route via the billing service",
        )
    )
    assert "🧠 Cerebrofy Review — auth/tokens.py:10" in body
    assert "🏛️ Architecture Rule" in body
    assert "Auth must not call billing" in body
    assert "**Suggestion:** Route via the billing service" in body


def test_format_inline_comment_without_line_or_suggestion() -> None:
    body = format_inline_comment(_finding(line=0, suggestion=""))
    assert "auth/tokens.py\n" in body or body.startswith("🧠 Cerebrofy Review — auth/tokens.py")
    assert "Suggestion:" not in body


def test_format_summary_includes_counts_reviewers_and_skips() -> None:
    report = ReviewReport(
        files_changed=2,
        neurons_changed=3,
        findings=[_finding(severity="error")],
        suggested_reviewers=[
            SuggestedReviewer(
                email="alice@co.com", lobe="auth", reason="sole author"
            )
        ],
        health_delta=HealthDelta(coupling=0.25, avg_blast=3.5),
        skipped_checks=["architecture rules (no rules file)"],
        max_blast_radius=6,
    )
    summary = format_summary(report, target="PR #7")

    assert summary.startswith("🧠 Cerebrofy Review Summary — PR #7")
    assert "Files Changed: **2**" in summary
    assert "Neurons Changed: **3**" in summary
    assert "Max Blast Radius: **6**" in summary
    assert "🔴 **1 high-severity finding(s)**" in summary
    assert "alice@co.com (auth lobe SME) — sole author" in summary
    assert "coupling +0.2500, avg blast +3.50" in summary
    assert "Skipped checks: architecture rules (no rules file)" in summary


def test_format_summary_clean_report() -> None:
    report = ReviewReport(files_changed=1, neurons_changed=1, clean_neurons=1)
    summary = format_summary(report)
    assert "No findings" in summary
    assert "1** changed neuron(s) passed" in summary
    assert "Skipped checks" not in summary


# ---------------------------------------------------------------------------
# ReviewReport payload
# ---------------------------------------------------------------------------


def test_review_report_counts_and_payload() -> None:
    report = ReviewReport(
        files_changed=2,
        neurons_changed=3,
        findings=[
            _finding(severity="error"),
            _finding(severity="warning", neuron="b"),
            _finding(severity="info", neuron="c"),
        ],
        health_delta=HealthDelta(coupling=-0.1, avg_blast=2.5),
    )

    assert (report.error_count, report.warning_count, report.info_count) == (1, 1, 1)
    payload = report.to_dict()
    assert set(payload) == {
        "files_changed",
        "neurons_changed",
        "findings",
        "suggested_reviewers",
        "health_delta",
        "summary",
    }
    assert payload["health_delta"] == {"coupling": -0.1, "avg_blast": 2.5}
    assert json.loads(report.to_json())["files_changed"] == 2


def test_review_report_payload_includes_optional_fields() -> None:
    report = ReviewReport(
        files_changed=0,
        neurons_changed=0,
        skipped_checks=["memory warnings (unreadable)"],
        post_result={"posted_inline": 1, "summary_posted": True, "errors": []},
    )
    payload = report.to_dict()
    assert payload["skipped_checks"] == ["memory warnings (unreadable)"]
    assert payload["post_result"]["posted_inline"] == 1


def test_post_result_payload_serialises() -> None:
    from cerebrofy.review.github_poster import PostResult

    ok = PostResult(posted_inline=2, summary_posted=True)
    assert ok.ok is True
    assert ok.to_dict() == {
        "posted_inline": 2,
        "summary_posted": True,
        "errors": [],
    }

    failed = PostResult(errors=["boom"])
    assert failed.ok is False
