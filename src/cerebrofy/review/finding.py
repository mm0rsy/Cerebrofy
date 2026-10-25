"""Review findings, severity scoring, and report rendering (Idea #17).

A :class:`Finding` is the unit of review output.  Its ``severity_score`` is the
shared ordering key for the whole report; the formula follows the product spec::

    base_severity * (blast_factor + memory_factor + coverage_factor)

where ``blast_factor = 1 + blast_radius / 50``, ``memory_factor`` is ``1.5``
when a warning memory exists for the neuron, and ``coverage_factor`` is ``1.3``
when the neuron has no test coverage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

CheckType = Literal[
    "blast_radius",
    "memory_violation",
    "arch_rule",
    "coverage_gap",
    "missing_caller_update",
    "coupling",
    "knowledge_silo",
]
Severity = Literal["error", "warning", "info"]

SEVERITY_ERROR: Severity = "error"
SEVERITY_WARNING: Severity = "warning"
SEVERITY_INFO: Severity = "info"

BASE_SEVERITY: dict[str, int] = {
    SEVERITY_ERROR: 3,
    SEVERITY_WARNING: 2,
    SEVERITY_INFO: 1,
}

SEVERITY_RANK: dict[str, int] = {
    SEVERITY_INFO: 1,
    SEVERITY_WARNING: 2,
    SEVERITY_ERROR: 3,
}

_SEVERITY_ICON: dict[str, str] = {
    SEVERITY_ERROR: "🔴",
    SEVERITY_WARNING: "🟡",
    SEVERITY_INFO: "🔵",
}

_CHECK_ICON: dict[str, str] = {
    "blast_radius": "💥",
    "memory_violation": "🧠",
    "arch_rule": "🏛️",
    "coverage_gap": "🧪",
    "missing_caller_update": "🔗",
    "coupling": "🕸️",
    "knowledge_silo": "👤",
}


def compute_severity_score(
    severity: str,
    blast_radius: int = 0,
    *,
    has_memory_warning: bool = False,
    uncovered: bool = False,
) -> float:
    """Return the non-linear severity score used to order findings.

    ``severity`` is the base bucket (``error`` = 3, ``warning`` = 2,
    ``info`` = 1).  Unknown severities fall back to ``info``.
    """
    base = BASE_SEVERITY.get(severity, BASE_SEVERITY[SEVERITY_INFO])
    blast_factor = 1.0 + max(0, blast_radius) / 50.0
    memory_factor = 1.5 if has_memory_warning else 1.0
    coverage_factor = 1.3 if uncovered else 1.0
    return round(base * (blast_factor + memory_factor + coverage_factor), 3)


@dataclass(frozen=False)
class Finding:
    """One actionable review finding anchored to a neuron and optional line."""

    check_type: str
    neuron: str
    neuron_lobe: str = ""
    file: str = ""
    line: int = 0
    severity: str = SEVERITY_INFO
    message: str = ""
    suggestion: str = ""
    severity_score: float = 0.0
    blast_radius: int = 0
    epistemic_confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.severity_score == 0.0:
            object.__setattr__(
                self,
                "severity_score",
                compute_severity_score(self.severity, self.blast_radius),
            )

    @property
    def severity_icon(self) -> str:
        return _SEVERITY_ICON.get(self.severity, "⚪")

    @property
    def check_icon(self) -> str:
        return _CHECK_ICON.get(self.check_type, "•")

    def to_dict(self) -> dict[str, Any]:
        """Return the spec-shaped JSON payload for this finding."""
        return {
            "check_type": self.check_type,
            "neuron": self.neuron,
            "file": self.file,
            "line": self.line,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "severity_score": self.severity_score,
        }


@dataclass(frozen=True)
class SuggestedReviewer:
    """A reviewer recommendation derived from knowledge-silo analysis."""

    email: str
    lobe: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"email": self.email, "lobe": self.lobe, "reason": self.reason}


@dataclass(frozen=True)
class HealthDelta:
    """Graph-health signals surfaced by the review."""

    coupling: float = 0.0
    avg_blast: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"coupling": self.coupling, "avg_blast": self.avg_blast}


@dataclass
class ReviewReport:
    """Full review result for one diff or pull request."""

    files_changed: int
    neurons_changed: int
    findings: list[Finding] = field(default_factory=list)
    suggested_reviewers: list[SuggestedReviewer] = field(default_factory=list)
    health_delta: HealthDelta = field(default_factory=HealthDelta)
    summary: str = ""
    skipped_checks: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    clean_neurons: int = 0
    max_blast_radius: int = 0
    post_result: dict[str, Any] | None = None

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == SEVERITY_ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == SEVERITY_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == SEVERITY_INFO)

    def to_dict(self) -> dict[str, Any]:
        """Return the MCP/CLI JSON payload for this report."""
        payload: dict[str, Any] = {
            "files_changed": self.files_changed,
            "neurons_changed": self.neurons_changed,
            "findings": [finding.to_dict() for finding in self.findings],
            "suggested_reviewers": [
                reviewer.to_dict() for reviewer in self.suggested_reviewers
            ],
            "health_delta": self.health_delta.to_dict(),
            "summary": self.summary,
        }
        if self.skipped_checks:
            payload["skipped_checks"] = list(self.skipped_checks)
        if self.post_result is not None:
            payload["post_result"] = self.post_result
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def filter_findings(findings: list[Finding], minimum: str = "all") -> list[Finding]:
    """Return findings at or above *minimum* severity (``error``/``warning``/``all``)."""
    if minimum == "all":
        return list(findings)
    threshold = SEVERITY_RANK.get(minimum, SEVERITY_RANK[SEVERITY_INFO])
    return [
        finding
        for finding in findings
        if SEVERITY_RANK.get(finding.severity, 0) >= threshold
    ]


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Sort by severity score descending, then severity rank, file, and line."""
    return sorted(
        findings,
        key=lambda finding: (
            -finding.severity_score,
            -SEVERITY_RANK.get(finding.severity, 0),
            finding.file,
            finding.line,
            finding.check_type,
        ),
    )


def format_inline_comment(finding: Finding) -> str:
    """Render a finding as a self-contained GitHub inline-comment body."""
    header = (
        f"🧠 Cerebrofy Review — {finding.file}"
        f"{f':{finding.line}' if finding.line else ''}"
    )
    lines = [
        header,
        "",
        f"{finding.severity_icon} **{finding.check_icon} {_check_title(finding.check_type)}**",
        "",
        finding.message,
    ]
    if finding.suggestion:
        lines.extend(["", f"**Suggestion:** {finding.suggestion}"])
    return "\n".join(lines)


def format_summary(report: ReviewReport, *, target: str | None = None) -> str:
    """Render the PR-level markdown summary for *report*."""
    heading = "🧠 Cerebrofy Review Summary"
    if target:
        heading += f" — {target}"

    lines = [
        heading,
        "",
        (f"Files Changed: **{report.files_changed}**  |  "
        f"Neurons Changed: **{report.neurons_changed}**  |  "
        f"Max Blast Radius: **{report.max_blast_radius}**"),
        "",
    ]

    if report.error_count:
        lines.append(f"🔴 **{report.error_count} high-severity finding(s)**")
    if report.warning_count:
        lines.append(f"🟡 **{report.warning_count} medium finding(s)**")
    if report.info_count:
        lines.append(f"🔵 **{report.info_count} informational finding(s)**")
    if not report.findings:
        lines.append("✅ No findings — every changed neuron passed all available checks.")
    if report.clean_neurons:
        lines.append(f"✅ **{report.clean_neurons}** changed neuron(s) passed with no issues.")

    if report.findings:
        lines.extend(["", "### Findings", ""])
        for finding in report.findings:
            location = finding.file + (f":{finding.line}" if finding.line else "")
            lines.append(
                f"- {finding.severity_icon} `{finding.check_type}` "
                f"**{finding.neuron}** ({location}) — {finding.message}"
            )

    if report.suggested_reviewers:
        lines.extend(["", "### Suggested reviewers", ""])
        for reviewer in report.suggested_reviewers:
            lines.append(
                f"- {reviewer.email} ({reviewer.lobe} lobe SME) — {reviewer.reason}"
            )

    lines.extend(
        [
            "",
            "### Health impact",
            "",
            (f"coupling {report.health_delta.coupling:+.4f}, "
            f"avg blast {report.health_delta.avg_blast:+.2f}"),
        ]
    )

    if report.skipped_checks:
        lines.extend(
            [
                "",
                "> ⚠️ Skipped checks: " + ", ".join(report.skipped_checks),
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def _check_title(check_type: str) -> str:
    titles = {
        "blast_radius": "Blast Radius",
        "memory_violation": "Memory Warning",
        "arch_rule": "Architecture Rule",
        "coverage_gap": "Test Coverage Gap",
        "missing_caller_update": "Missing Caller Update",
        "coupling": "Cross-Lobe Coupling",
        "knowledge_silo": "Knowledge Silo",
    }
    return titles.get(check_type, check_type.replace("_", " ").title())
