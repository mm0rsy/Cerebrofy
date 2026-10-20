"""Turn scan results into an ordered, effort-scored upgrade plan.

Ordering follows the migration dependency direction:

1. ``base`` changes (base classes / ``class Config`` blocks) — every call site
   depends on these being in place first.
2. ``call`` changes, ordered by the affected neuron's depth-2 blast radius
   (highest first) so the widest-reaching call sites get attention early.
3. ``validator`` changes.
4. everything else.

Effort uses the product spec formula::

    effort_score = sum(1 + blast_radius(neuron) * 0.1 for neuron in affected)

``AVG_MINUTES_PER_EFFORT_POINT`` converts the score into a human time estimate.
The blast radius is the real depth-2 caller count from the graph
(:func:`cerebrofy.analysis.blast_radius.bfs_callers`), excluding
``RUNTIME_BOUNDARY`` edges per Law II.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.analysis.blast_radius import bfs_callers
from cerebrofy.upgrade.manifest import Change, Manifest
from cerebrofy.upgrade.scanner import ChangeUsage, ScanResult

AVG_MINUTES_PER_EFFORT_POINT = 2.5
_CATEGORY_ORDER = {"base": 0, "call": 1, "validator": 2, "other": 3}


@dataclass(frozen=True)
class PlanStep:
    """One actionable migration step (one manifest change)."""

    step_number: int
    change_index: int
    change_type: str
    old_api: str
    new_api: str
    severity: str
    category: str
    description: str
    neurons_to_update: list[str]
    files: list[str]
    site_count: int
    loc_estimate: int
    effort_score: float
    max_blast_radius: int
    auto_fix: bool


@dataclass
class UpgradePlan:
    """The complete upgrade navigator result for one package/version pair."""

    package: str
    from_version: str
    to_version: str
    manifest_source: str
    steps: list[PlanStep] = field(default_factory=list)
    total_effort_hours: float = 0.0
    risk: str = "LOW"
    total_neurons: int = 0
    total_sites: int = 0
    files_affected: int = 0
    unused_changes: int = 0

    @property
    def breaking_steps(self) -> list[PlanStep]:
        return [step for step in self.steps if step.severity == "breaking"]

    @property
    def auto_fixable_steps(self) -> list[int]:
        return [step.step_number for step in self.steps if step.auto_fix]

    def to_dict(self) -> dict[str, object]:
        """Return the MCP/JSON output schema (plus a few diagnostic fields)."""
        return {
            "package": self.package,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "manifest_source": self.manifest_source,
            "breaking_changes": [
                {
                    "type": step.change_type,
                    "old_api": step.old_api,
                    "new_api": step.new_api,
                    "severity": step.severity,
                    "affected_neurons": step.neurons_to_update,
                    "effort_score": step.effort_score,
                    "sites": step.site_count,
                    "files": step.files,
                }
                for step in self.breaking_steps
            ],
            "steps": [
                {
                    "step_number": step.step_number,
                    "description": step.description,
                    "neurons_to_update": step.neurons_to_update,
                    "loc_estimate": step.loc_estimate,
                    "change_type": step.change_type,
                    "old_api": step.old_api,
                    "new_api": step.new_api,
                    "severity": step.severity,
                    "sites": step.site_count,
                    "files": step.files,
                    "effort_score": step.effort_score,
                    "max_blast_radius": step.max_blast_radius,
                    "auto_fix": step.auto_fix,
                }
                for step in self.steps
            ],
            "total_effort_hours": self.total_effort_hours,
            "risk": self.risk,
            "total_neurons": self.total_neurons,
            "total_sites": self.total_sites,
            "files_affected": self.files_affected,
            "unused_changes": self.unused_changes,
            "auto_fixable_steps": self.auto_fixable_steps,
            "auto_fix_results": [],
        }


# ---------------------------------------------------------------------------
# Blast radius cache
# ---------------------------------------------------------------------------

def _blast_counts(neuron_ids: list[str], conn: sqlite3.Connection) -> dict[str, int]:
    """Depth-2 caller counts for *neuron_ids* (cached per call)."""
    counts: dict[str, int] = {}
    for neuron_id in neuron_ids:
        try:
            depth1, depth2, _runtime = bfs_callers(neuron_id, conn, max_depth=2)
        except sqlite3.Error:
            counts[neuron_id] = 0
            continue
        counts[neuron_id] = len({n.id for n in depth1} | {n.id for n in depth2})
    return counts


def _risk(total_hours: float, max_blast: int, total_neurons: int) -> str:
    if total_hours >= 8.0 or max_blast >= 15 or total_neurons >= 30:
        return "HIGH"
    if total_hours >= 2.0 or max_blast >= 5 or total_neurons >= 10:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _description(change: Change, site_count: int, files: int) -> str:
    if change.category == "base":
        prefix = "Update base classes / config blocks"
    elif change.category == "validator":
        prefix = "Update validators"
    elif change.category == "call":
        prefix = "Update call sites"
    else:
        prefix = "Update usages"
    file_word = "file" if files == 1 else "files"
    return f"{prefix}: {change.old} → {change.new} ({site_count} sites across {files} {file_word})"


def _selected_usages(scan: ScanResult, breaking_only: bool) -> list[ChangeUsage]:
    usages = [usage for usage in scan.usages_for(breaking_only=breaking_only) if usage.sites]
    return usages


def build_plan(
    package: str,
    manifest: Manifest,
    scan: ScanResult,
    conn: sqlite3.Connection,
    *,
    breaking_only: bool = False,
) -> UpgradePlan:
    """Build the ordered migration plan from a completed scan."""
    usages = _selected_usages(scan, breaking_only)
    all_neuron_ids = sorted({nid for usage in usages for nid in usage.affected_neurons})
    blast = _blast_counts(all_neuron_ids, conn)

    def max_blast_for(usage: ChangeUsage) -> int:
        return max((blast.get(nid, 0) for nid in usage.affected_neurons), default=0)

    ordered = sorted(
        usages,
        key=lambda u: (
            _CATEGORY_ORDER.get(u.change.category, 3),
            -max_blast_for(u),
            u.change_index,
        ),
    )

    steps: list[PlanStep] = []
    total_effort = 0.0
    for step_number, usage in enumerate(ordered, start=1):
        neurons = sorted(usage.affected_neurons, key=lambda nid: (-blast.get(nid, 0), nid))
        effort = sum(1 + blast.get(nid, 0) * 0.1 for nid in usage.affected_neurons)
        total_effort += effort
        loc_estimate = max(1, len(usage.sites))
        steps.append(
            PlanStep(
                step_number=step_number,
                change_index=usage.change_index,
                change_type=usage.change.type,
                old_api=usage.change.old,
                new_api=usage.change.new,
                severity=usage.change.severity,
                category=usage.change.category,
                description=_description(usage.change, len(usage.sites), len(usage.files)),
                neurons_to_update=neurons,
                files=usage.files,
                site_count=len(usage.sites),
                loc_estimate=loc_estimate,
                effort_score=round(effort, 2),
                max_blast_radius=max_blast_for(usage),
                auto_fix=usage.change.auto_fix,
            )
        )

    total_hours = round(total_effort * AVG_MINUTES_PER_EFFORT_POINT / 60.0, 1)
    max_blast = max((step.max_blast_radius for step in steps), default=0)
    selected_neurons = {nid for step in steps for nid in step.neurons_to_update}
    files = {file for step in steps for file in step.files}
    return UpgradePlan(
        package=package,
        from_version=manifest.from_version,
        to_version=manifest.to_version,
        manifest_source=manifest.source,
        steps=steps,
        total_effort_hours=total_hours,
        risk=_risk(total_hours, max_blast, len(selected_neurons)),
        total_neurons=len(selected_neurons),
        total_sites=sum(step.site_count for step in steps),
        files_affected=len(files),
        unused_changes=max(0, len(manifest.changes) - len(_selected_usages(scan, False))),
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

_RISK_ICON = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}


def render_markdown(
    plan: UpgradePlan,
    *,
    validation: "object | None" = None,
    fix_results: Sequence[object] | None = None,
) -> str:
    """Render the plan as human-readable Markdown.

    *validation* and *fix_results* are duck-typed to avoid a planner→validator
    import cycle (both expose ``to_dict``/``step`` attributes).
    """
    version_label = f"{plan.from_version or '?'} → {plan.to_version or '?'}"
    icon = _RISK_ICON.get(plan.risk, "🟡")
    lines: list[str] = [
        f"# 🧠 Cerebrofy — Upgrade Navigator: {plan.package} {version_label}",
        "",
        f"Scanned the indexed Python files and found **{plan.total_sites} sites** "
        f"across **{plan.total_neurons} neurons** in **{plan.files_affected} files**.",
        "",
        f"**Effort Estimate:** ~{plan.total_effort_hours:g} hours  |  "
        f"**Risk:** {icon} {plan.risk}  |  "
        f"**Manifest:** `{plan.manifest_source}`",
        "",
        "## Breaking Changes Affecting Your Code",
        "",
    ]
    if plan.breaking_steps:
        lines.extend(
            [
                "| Change | Sites | Neurons | Effort |",
                "|---|---:|---:|---:|",
            ]
        )
        for step in plan.breaking_steps:
            lines.append(
                f"| `{step.old_api}` → `{step.new_api}` | {step.site_count} "
                f"| {len(step.neurons_to_update)} | {step.effort_score:g} |"
            )
    else:
        lines.append("_No breaking changes affect this codebase._")
    lines.extend(["", "## Step-by-Step Migration Plan", ""])
    if not plan.steps:
        lines.append("_Nothing to do — no affected API usage was found._")
    for step in plan.steps:
        fix_tag = " _(auto-fixable)_" if step.auto_fix else ""
        lines.append(f"### Step {step.step_number}: {step.description}{fix_tag}")
        lines.append("")
        for neuron_id in step.neurons_to_update:
            prefix = f"- `{neuron_id}`"
            blast = step.max_blast_radius
            lines.append(f"{prefix} (max blast: {blast})")
        lines.append("")

    if plan.auto_fixable_steps:
        steps_arg = ",".join(str(n) for n in plan.auto_fixable_steps)
        lines.append(
            f"Auto-fix available for steps {steps_arg}: "
            f"`cerebrofy upgrade {plan.package} --auto-fix --step {steps_arg}`"
        )
        lines.append("")

    if fix_results:
        lines.extend(["## Auto-fix Results", ""])
        for result in fix_results:
            data = result.to_dict() if hasattr(result, "to_dict") else {}
            step = data.get("step", "?")
            fixed = data.get("neurons_fixed", 0)
            errors = data.get("errors", [])
            lines.append(f"- Step {step}: fixed {fixed} neuron(s), {len(errors)} error(s)")
            for error in errors:
                lines.append(f"  - {error}")
        lines.append("")

    if validation is not None:
        lines.append("## Post-upgrade Validation")
        lines.append("")
        if hasattr(validation, "to_markdown"):
            lines.append(validation.to_markdown())
        else:
            lines.append(str(validation))
        lines.append("")

    lines.append(
        f"Run `cerebrofy upgrade {plan.package} --validate` after applying the steps "
        "to confirm no old API patterns remain."
    )
    return "\n".join(lines)


def plan_file_paths(plan: UpgradePlan, root: Path) -> list[Path]:
    """Return absolute file paths touched by *plan* (kept for callers/tests)."""
    return [root / file for step in plan.steps for file in step.files]
