"""Unit tests for planning/formatter.py — exact JSON schema + Markdown rendering."""

from __future__ import annotations

import json

from cerebrofy.planning.extractor import ClusterNeuron
from cerebrofy.planning.formatter import plan_to_dict, plan_to_json, plan_to_markdown
from cerebrofy.planning.planner import RefactorPlan
from cerebrofy.planning.sequence import MigrationStep

_EXPECTED_TOP_LEVEL = {
    "cluster",
    "proposed_structure",
    "callers_to_update",
    "steps",
    "estimated_hours",
    "files_affected",
}


def _neuron(nid: str, name: str, file: str, line: int = 1, score: float = 0.9) -> ClusterNeuron:
    return ClusterNeuron(
        id=nid, name=name, file=file, line_start=line, line_end=line + 9,
        relevance_score=score,
    )


def _plan(**overrides: object) -> RefactorPlan:
    callee = _neuron("pay.py::charge", "charge", "pay.py", line=5, score=0.95)
    caller = _neuron("pay.py::refund", "refund", "pay.py", line=40, score=0.8)
    ext = _neuron("api.py::route", "route", "api.py", line=12, score=0.0)
    defaults: dict[str, object] = dict(
        description="extract the payment logic into a payments service.",
        cluster=[callee, caller],
        seeds=[callee],
        callers_to_update=[ext],
        new_module="payments",
        proposed_files=["payments/pay.py"],
        file_map={"pay.py": "payments/pay.py"},
        steps=[
            MigrationStep(1, "Create skeleton for 'payments/' — 1 new file(s): pay.py", [], False),
            MigrationStep(2, "Move 2 neuron(s) from pay.py → payments/pay.py", 
                         ["pay.py::charge", "pay.py::refund"], False),
            MigrationStep(3, "Update 1 caller(s) across 1 file(s) to import from 'payments/'",
                         ["api.py::route"], False),
            MigrationStep(4, "Remove backward-compat re-exports from 1 file(s) "
                         "and run the test suite", ["pay.py::charge", "pay.py::refund"], False),
        ],
        estimated_hours=1.1,
        files_affected=3,
        blast_radius_label="MEDIUM",
    )
    defaults.update(overrides)
    return RefactorPlan(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# plan_to_dict — exact schema
# ---------------------------------------------------------------------------

def test_plan_to_dict_has_exact_top_level_keys() -> None:
    data = plan_to_dict(_plan())
    assert set(data) == _EXPECTED_TOP_LEVEL


def test_plan_to_dict_cluster_shape() -> None:
    data = plan_to_dict(_plan())
    assert data["cluster"] == [
        {"name": "charge", "file": "pay.py", "relevance_score": 0.95},
        {"name": "refund", "file": "pay.py", "relevance_score": 0.8},
    ]
    assert set(data["cluster"][0]) == {"name", "file", "relevance_score"}


def test_plan_to_dict_proposed_structure_shape() -> None:
    data = plan_to_dict(_plan())
    assert data["proposed_structure"] == {
        "new_module": "payments",
        "files": ["payments/pay.py"],
    }
    assert set(data["proposed_structure"]) == {"new_module", "files"}


def test_plan_to_dict_callers_shape_uses_line_int() -> None:
    data = plan_to_dict(_plan())
    assert data["callers_to_update"] == [{"name": "route", "file": "api.py", "line": 12}]
    assert set(data["callers_to_update"][0]) == {"name", "file", "line"}


def test_plan_to_dict_caller_without_line_defaults_to_zero() -> None:
    ext = ClusterNeuron(
        id="api.py::route", name="route", file="api.py",
        line_start=None, line_end=None, relevance_score=0.0,
    )
    data = plan_to_dict(_plan(callers_to_update=[ext]))
    assert data["callers_to_update"][0]["line"] == 0


def test_plan_to_dict_steps_shape() -> None:
    data = plan_to_dict(_plan())
    assert len(data["steps"]) == 4
    for step in data["steps"]:
        assert set(step) == {"step_number", "description", "neurons_affected", "callers_break"}
    assert data["steps"][1]["neurons_affected"] == ["pay.py::charge", "pay.py::refund"]
    assert data["steps"][1]["callers_break"] is False


def test_plan_to_json_round_trips_to_dict() -> None:
    plan = _plan()
    assert json.loads(plan_to_json(plan)) == plan_to_dict(plan)


def test_plan_to_dict_relevance_scores_rounded() -> None:
    neuron = _neuron("x.py::f", "f", "x.py", score=0.66666666)
    data = plan_to_dict(_plan(cluster=[neuron], seeds=[neuron]))
    assert data["cluster"][0]["relevance_score"] == 0.6667


# ---------------------------------------------------------------------------
# plan_to_markdown
# ---------------------------------------------------------------------------

def test_markdown_has_all_core_sections() -> None:
    text = plan_to_markdown(_plan())
    assert text.startswith("# Refactoring Plan: Extract the payment logic into a payments service")
    assert "## What Cerebrofy Found" in text
    assert "## Proposed Structure" in text
    assert "## Callers to Update (1 location(s) across 1 file(s))" in text
    assert "## Step-by-Step Migration Plan" in text
    assert "**Estimated effort:** 1.1 hours" in text
    assert "**Files affected:** 3" in text
    assert "**Blast radius:** MEDIUM" in text


def test_markdown_seed_and_expansion_relevance_labels() -> None:
    text = plan_to_markdown(_plan())
    assert "relevance 0.95" in text  # seed
    assert "cohesion 0.80 (graph expansion)" in text  # expansion neuron


def test_markdown_context_sections_omitted_when_empty() -> None:
    text = plan_to_markdown(_plan())
    assert "Plan Context (from agent memories)" not in text
    assert "Intent Warnings" not in text
    assert "Execution Handoff" not in text


def test_markdown_context_sections_rendered_when_present() -> None:
    plan = _plan(
        memory_context=["decision: payments split approved"],
        avoid_pattern_warnings=["avoid_pattern 'god-object' matches the affected code"],
        handoff_summary="12 neuron(s) packed into 100/200 tokens",
    )
    text = plan_to_markdown(plan)
    assert "## Plan Context (from agent memories)" in text
    assert "- decision: payments split approved" in text
    assert "## ⚠️ Intent Warnings (intent.yaml)" in text
    assert "- avoid_pattern 'god-object' matches the affected code" in text
    assert "## Execution Handoff" in text
    assert "12 neuron(s) packed into 100/200 tokens" in text


def test_markdown_no_callers_marker() -> None:
    text = plan_to_markdown(_plan(callers_to_update=[]))
    assert "_No external callers — this extraction is self-contained._" in text


def test_markdown_runtime_boundary_warning_footer_and_step() -> None:
    plan = _plan(
        runtime_boundary_callers=["framework::hook"],
        steps=[
            MigrationStep(1, "Create skeleton", [], False),
            MigrationStep(2, "⚠️  1 RUNTIME_BOUNDARY caller(s) detected — manual",
                         ["framework::hook"], True),
        ],
    )
    text = plan_to_markdown(plan)
    assert "callers break: ⚠️ yes" in text
    assert "1 RUNTIME_BOUNDARY caller(s) cross process/framework boundaries" in text


def test_markdown_truncates_long_neuron_lists() -> None:
    ids = [f"a.py::f{i}" for i in range(8)]
    neurons = [_neuron(nid, f"f{i}", "a.py", line=i + 1) for i, nid in enumerate(ids)]
    plan = _plan(
        cluster=neurons,
        seeds=[],
        steps=[MigrationStep(1, "Move 8 neuron(s)", ids, False)],
    )
    text = plan_to_markdown(plan)
    assert "… (+2 more)" in text
