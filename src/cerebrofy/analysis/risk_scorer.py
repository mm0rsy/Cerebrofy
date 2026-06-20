"""Risk score computation for blast radius analysis."""

from __future__ import annotations


def compute_risk_score(
    direct_callers: int,
    indirect_callers: int,
    total_lobes: int,
    lobes_calling: int,
    test_coverage_ratio: float,
) -> float:
    """Return a raw risk score using the formula from the spec.

    risk = (direct * 1.0 + indirect * 0.4) * lobe_coupling / max(test_coverage_ratio, 0.05)
    lobe_coupling = lobes_calling / max(total_lobes, 1)
    """
    lobe_coupling = lobes_calling / max(total_lobes, 1)
    weighted_callers = direct_callers * 1.0 + indirect_callers * 0.4
    return weighted_callers * lobe_coupling / max(test_coverage_ratio, 0.05)


def risk_label(score: float) -> str:
    """Bucket a raw risk score into LOW / MEDIUM / HIGH."""
    if score >= 10.0:
        return "HIGH"
    if score >= 3.0:
        return "MEDIUM"
    return "LOW"


def risk_icon(label: str) -> str:
    return {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(label, "⚪")
