"""Markdown + JSON rendering for refactor plans (Idea #12).

``plan_to_dict`` emits the spec's output schema — the JSON keys are exact
(``cluster``, ``proposed_structure``, ``callers_to_update``, ``steps``,
``estimated_hours``, ``files_affected``); all extra context (memories, intent
warnings, execution handoff) is rendered in Markdown only.
"""

from __future__ import annotations

import json
from typing import Any

from cerebrofy.planning.planner import RefactorPlan

# Display cap: at most 6 neuron names are shown in a Markdown list item before
# truncating with "… (+N more)". This keeps terminal columns readable and
# mirrors the limit already enforced in CLI plan output.
MAX_DISPLAY_NAMES_PER_FILE = 6


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def plan_to_dict(plan: RefactorPlan) -> dict[str, Any]:
    """Return the plan as the exact structure defined by the spec schema."""
    return {
        "cluster": [
            {
                "name": neuron.name,
                "file": neuron.file,
                "relevance_score": round(neuron.relevance_score, 4),
            }
            for neuron in plan.cluster
        ],
        "proposed_structure": {
            "new_module": plan.new_module,
            "files": list(plan.proposed_files),
        },
        "callers_to_update": [
            {
                "name": caller.name,
                "file": caller.file,
                "line": int(caller.line_start or 0),
            }
            for caller in plan.callers_to_update
        ],
        "steps": [
            {
                "step_number": step.step_number,
                "description": step.description,
                "neurons_affected": list(step.neurons_affected),
                "callers_break": step.callers_break,
            }
            for step in plan.steps
        ],
        "estimated_hours": plan.estimated_hours,
        "files_affected": plan.files_affected,
    }


def plan_to_json(plan: RefactorPlan) -> str:
    """Render the plan as pretty-printed JSON (spec schema)."""
    return json.dumps(plan_to_dict(plan), indent=2)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _title(description: str) -> str:
    text = description.strip().rstrip(".")
    return text[:1].upper() + text[1:] if text else "Refactoring Plan"


def _names_for(ids: list[str], by_id: dict[str, str]) -> str:
    names = [by_id.get(nid, nid) for nid in ids]
    if len(names) > MAX_DISPLAY_NAMES_PER_FILE:
        shown = ", ".join(names[:MAX_DISPLAY_NAMES_PER_FILE])
        return f"{shown}, … (+{len(names) - MAX_DISPLAY_NAMES_PER_FILE} more)"
    return ", ".join(names)


def _neuron_by_id(plan: RefactorPlan) -> dict[str, str]:
    by_id = {n.id: n.name for n in plan.cluster}
    by_id.update({c.id: c.name for c in plan.callers_to_update})
    return by_id


def _cluster_section(plan: RefactorPlan) -> list[str]:
    seed_ids = {seed.id for seed in plan.seeds}
    expansions = len(plan.cluster) - len(seed_ids)
    lines = ["## What Cerebrofy Found", ""]
    lines.append(
        f"Semantic search identified {len(seed_ids)} seed(s) matching "
        f"\"{plan.description}\""
        + (
            f"; graph expansion added {expansions} densely connected neuron(s)."
            if expansions
            else "."
        )
    )
    lines.append("")
    for neuron in plan.cluster:
        suffix = (
            f"relevance {neuron.relevance_score:.2f}"
            if neuron.id in seed_ids
            else f"cohesion {neuron.relevance_score:.2f} (graph expansion)"
        )
        lines.append(f"- `{neuron.file}::{neuron.name}` — {suffix}")
    lines.append("")
    return lines


def _structure_section(plan: RefactorPlan) -> list[str]:
    inverse: dict[str, str] = {}
    for source, target in plan.file_map.items():
        inverse[target] = source

    lines = ["## Proposed Structure", "", f"New module: `{plan.new_module}/`", "", "```"]
    lines.append(f"{plan.new_module}/")
    files = plan.proposed_files
    for index, target in enumerate(files):
        branch = "└──" if index == len(files) - 1 else "├──"
        source = inverse.get(target, "")
        movers = [
            n for n in plan.cluster if n.file == source
        ]
        names = ", ".join(n.name for n in movers[:MAX_DISPLAY_NAMES_PER_FILE])
        if len(movers) > MAX_DISPLAY_NAMES_PER_FILE:
            names += ", …"
        origin = f"  ← {source}" + (f" ({names})" if names else "")
        lines.append(f"{branch} {target}{origin}")
    lines.append("```")
    lines.append("")
    return lines


def _context_section(plan: RefactorPlan) -> list[str]:
    lines: list[str] = []
    if plan.memory_context:
        lines.append("## Plan Context (from agent memories)")
        lines.append("")
        lines.extend(f"- {item}" for item in plan.memory_context)
        lines.append("")
    if plan.avoid_pattern_warnings:
        lines.append("## ⚠️ Intent Warnings (intent.yaml)")
        lines.append("")
        lines.extend(f"- {warning}" for warning in plan.avoid_pattern_warnings)
        lines.append("")
    return lines


def _callers_section(plan: RefactorPlan) -> list[str]:
    callers = plan.callers_to_update
    files = {c.file for c in callers}
    lines = [
        f"## Callers to Update ({len(callers)} location(s) across {len(files)} file(s))",
        "",
    ]
    if not callers:
        lines.append("_No external callers — this extraction is self-contained._")
        lines.append("")
        return lines
    for caller in callers:
        lines.append(f"- `{caller.file}:{caller.line_start or 0}` — `{caller.name}`")
    lines.append("")
    return lines


def _steps_section(plan: RefactorPlan) -> list[str]:
    by_id = _neuron_by_id(plan)
    lines = ["## Step-by-Step Migration Plan", ""]
    for step in plan.steps:
        break_note = "callers break: ⚠️ yes" if step.callers_break else "callers break: no"
        lines.append(f"**Step {step.step_number}: {step.description}** ({break_note})")
        if step.neurons_affected:
            lines.append(f"  - neurons affected: {_names_for(step.neurons_affected, by_id)}")
        lines.append("")
    return lines


def _handoff_section(plan: RefactorPlan) -> list[str]:
    if not plan.handoff_summary:
        return []
    return [
        "## Execution Handoff",
        "",
        plan.handoff_summary,
        "",
        "Approve this plan, then hand it to an AI agent with "
        "`cerebrofy_impact` verification at each step.",
        "",
    ]


def plan_to_markdown(plan: RefactorPlan) -> str:
    """Render the plan as a human-reviewable Markdown checklist."""
    lines: list[str] = [f"# Refactoring Plan: {_title(plan.description)}", ""]
    lines.extend(_cluster_section(plan))
    lines.extend(_structure_section(plan))
    lines.extend(_context_section(plan))
    lines.extend(_callers_section(plan))
    lines.extend(_steps_section(plan))
    lines.extend(_handoff_section(plan))
    lines.append(
        f"**Estimated effort:** {plan.estimated_hours:g} hours | "
        f"**Files affected:** {plan.files_affected} | "
        f"**Blast radius:** {plan.blast_radius_label}"
    )
    if plan.runtime_boundary_callers:
        lines.append("")
        lines.append(
            f"⚠️  {len(plan.runtime_boundary_callers)} RUNTIME_BOUNDARY caller(s) "
            "cross process/framework boundaries — verify manually."
        )
    return "\n".join(lines)
