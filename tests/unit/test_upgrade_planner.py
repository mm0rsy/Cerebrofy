"""Unit tests for upgrade/planner.py."""

from __future__ import annotations

from pathlib import Path

from cerebrofy.upgrade.manifest import parse_manifest
from cerebrofy.upgrade.planner import _risk, build_plan
from cerebrofy.upgrade.scanner import scan_package
from tests.unit.upgrade_helpers import make_index_repo, open_ro

SOURCE = """\
from pydantic import BaseModel, validator

class Base(BaseModel):
    class Config:
        extra = "forbid"

    @validator("x")
    def check(cls, value):
        return value

def serialize(obj):
    return obj.dict()

def as_json(obj):
    return obj.json()
"""


def _manifest() -> object:
    return parse_manifest(
        {
            "package": "pydantic",
            "from_version": ">=1,<2",
            "to_version": ">=2",
            "changes": [
                {
                    "type": "changed",
                    "old": "class Config",
                    "new": "model_config = ConfigDict(...)",
                    "severity": "breaking",
                    "category": "base",
                    "match": r"^\s*class\s+Config\b",
                    "auto_fix": False,
                },
                {
                    "type": "rename",
                    "old": ".dict()",
                    "new": ".model_dump()",
                    "severity": "breaking",
                    "category": "call",
                    "match": r"\.dict\s*\(",
                    "auto_fix": True,
                },
                {
                    "type": "rename",
                    "old": ".json()",
                    "new": ".model_dump_json()",
                    "severity": "deprecated",
                    "category": "call",
                    "match": r"\.json\s*\(",
                    "auto_fix": True,
                },
                {
                    "type": "rename",
                    "old": "@validator",
                    "new": "@field_validator",
                    "severity": "breaking",
                    "category": "validator",
                    "match": r"@validator\b",
                    "auto_fix": True,
                },
            ],
        }
    )


NODES = [
    ("m.py::m", "m", "m.py", "module", 1, 14),
    ("m.py::Base", "Base", "m.py", "class", 3, 9),
    ("m.py::check", "check", "m.py", "function", 7, 9),
    ("m.py::serialize", "serialize", "m.py", "function", 11, 12),
    ("m.py::as_json", "as_json", "m.py", "function", 14, 15),
    ("m.py::caller1", "caller1", "m.py", "function", 17, 18),
    ("m.py::caller2", "caller2", "m.py", "function", 20, 21),
    ("m.py::deep", "deep", "m.py", "function", 23, 24),
    ("m.py::json_caller", "json_caller", "m.py", "function", 26, 27),
]

EDGES = [
    ("m.py::caller1", "m.py::serialize", "LOCAL_CALL", "m.py"),
    ("m.py::caller2", "m.py::serialize", "LOCAL_CALL", "m.py"),
    ("m.py::deep", "m.py::caller1", "LOCAL_CALL", "m.py"),
    ("m.py::json_caller", "m.py::as_json", "LOCAL_CALL", "m.py"),
]


def _scan(tmp_path: Path):  # type: ignore[no-untyped-def]
    db_path = make_index_repo(tmp_path, {"m.py": SOURCE}, NODES, EDGES)
    conn = open_ro(db_path)
    manifest = _manifest()
    scan = scan_package("pydantic", manifest, conn, tmp_path)
    return manifest, scan, conn


class TestBuildPlan:
    def test_ordering_and_blast_radius(self, tmp_path: Path) -> None:
        manifest, scan, conn = _scan(tmp_path)
        try:
            plan = build_plan("pydantic", manifest, scan, conn, breaking_only=True)
        finally:
            conn.close()

        assert [step.category for step in plan.steps] == ["base", "call", "validator"]
        dict_step = plan.steps[1]
        assert dict_step.old_api == ".dict()"
        assert dict_step.max_blast_radius == 3
        assert dict_step.effort_score == 1.3
        assert dict_step.site_count == 1
        assert dict_step.loc_estimate == 1

    def test_breaking_only_filters_deprecated(self, tmp_path: Path) -> None:
        manifest, scan, conn = _scan(tmp_path)
        try:
            breaking = build_plan("pydantic", manifest, scan, conn, breaking_only=True)
            all_changes = build_plan("pydantic", manifest, scan, conn, breaking_only=False)
        finally:
            conn.close()
        assert ".json()" not in [step.old_api for step in breaking.steps]
        assert ".json()" in [step.old_api for step in all_changes.steps]
        json_step = next(s for s in all_changes.steps if s.old_api == ".json()")
        assert json_step.max_blast_radius == 1

    def test_call_steps_sorted_by_blast_descending(self, tmp_path: Path) -> None:
        manifest, scan, conn = _scan(tmp_path)
        try:
            plan = build_plan("pydantic", manifest, scan, conn, breaking_only=False)
        finally:
            conn.close()
        call_steps = [step for step in plan.steps if step.category == "call"]
        assert [step.old_api for step in call_steps] == [".dict()", ".json()"]

    def test_output_schema_and_effort_hours(self, tmp_path: Path) -> None:
        manifest, scan, conn = _scan(tmp_path)
        try:
            plan = build_plan("pydantic", manifest, scan, conn)
        finally:
            conn.close()
        payload = plan.to_dict()
        assert payload["package"] == "pydantic"
        assert payload["total_effort_hours"] == plan.total_effort_hours
        assert payload["risk"] in {"LOW", "MEDIUM", "HIGH"}
        step = payload["steps"][0]
        assert isinstance(step, dict)
        assert {"step_number", "description", "neurons_to_update", "loc_estimate"} <= set(step)
        assert all(
            {"type", "old_api", "new_api", "severity", "affected_neurons", "effort_score"}
            <= set(change)
            for change in payload["breaking_changes"]
        )

    def test_risk_thresholds(self) -> None:
        assert _risk(0.2, 1, 2) == "LOW"
        assert _risk(2.5, 1, 2) == "MEDIUM"
        assert _risk(8.0, 1, 2) == "HIGH"
        assert _risk(0.1, 15, 2) == "HIGH"
        assert _risk(0.1, 1, 30) == "HIGH"

    def test_empty_scan_gives_empty_plan(self, tmp_path: Path) -> None:
        db_path = make_index_repo(tmp_path, {"empty.py": "x = 1\n"}, [("empty.py::empty", "empty", "empty.py", "module", 1, 1)])
        conn = open_ro(db_path)
        try:
            manifest = _manifest()
            scan = scan_package("pydantic", manifest, conn, tmp_path)
            plan = build_plan("pydantic", manifest, scan, conn)
        finally:
            conn.close()
        assert plan.steps == []
        assert plan.risk == "LOW"
