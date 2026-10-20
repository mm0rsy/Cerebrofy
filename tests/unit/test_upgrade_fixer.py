"""Unit tests for upgrade/fixer.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrofy.upgrade.fixer import FixerError, apply_fixes
from cerebrofy.upgrade.manifest import Manifest, parse_manifest
from cerebrofy.upgrade.planner import build_plan
from cerebrofy.upgrade.scanner import ChangeUsage, ScanResult, UsageSite, scan_package
from tests.unit.upgrade_helpers import make_index_repo, open_ro

SOURCE = """\
from pydantic import BaseModel, validator

class User(BaseModel):
    name: str

    @validator("name")
    def check(cls, value):
        return value

def serialize(user):
    return user.dict()

def as_json(user):
    return user.json()
"""


def _manifest() -> Manifest:
    return parse_manifest(
        {
            "package": "pydantic",
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
                    "old": "@validator",
                    "new": "@field_validator",
                    "severity": "breaking",
                    "category": "validator",
                    "match": r"@validator\b",
                    "auto_fix": True,
                },
                {
                    "type": "rename",
                    "old": "pydantic.validator",
                    "new": "pydantic.field_validator",
                    "severity": "breaking",
                    "category": "validator",
                    "match": r"^\s*from\s+pydantic\s+import\s+.*\bvalidator\b",
                    "auto_fix": True,
                },
            ],
        }
    )


NODES = [
    ("u.py::u", "u", "u.py", "module", 1, 15),
    ("u.py::User", "User", "u.py", "class", 3, 9),
    ("u.py::check", "check", "u.py", "function", 7, 9),
    ("u.py::serialize", "serialize", "u.py", "function", 11, 12),
    ("u.py::as_json", "as_json", "u.py", "function", 14, 15),
]


def _setup(tmp_path: Path, manifest: Manifest):  # type: ignore[no-untyped-def]
    db_path = make_index_repo(tmp_path, {"u.py": SOURCE}, NODES)
    conn = open_ro(db_path)
    scan = scan_package("pydantic", manifest, conn, tmp_path)
    plan = build_plan("pydantic", manifest, scan, conn)
    return conn, scan, plan


def _step_for(plan, old_api: str) -> int:  # type: ignore[no-untyped-def]
    return next(step.step_number for step in plan.steps if step.old_api == old_api)


class TestApplyFixes:
    def test_renames_calls_decorator_and_import(self, tmp_path: Path) -> None:
        manifest = _manifest()
        conn, scan, plan = _setup(tmp_path, manifest)
        conn.close()

        results = apply_fixes(plan, manifest, scan, tmp_path)
        text = (tmp_path / "u.py").read_text(encoding="utf-8")

        assert "from pydantic import BaseModel, field_validator" in text
        assert "@field_validator" in text
        assert "user.model_dump()" in text
        assert "user.json()" in text
        assert all(not result.errors for result in results)
        assert sum(result.sites_fixed for result in results) == 3

    def test_explicit_step_selection(self, tmp_path: Path) -> None:
        manifest = _manifest()
        conn, scan, plan = _setup(tmp_path, manifest)
        conn.close()
        dict_step = _step_for(plan, ".dict()")

        results = apply_fixes(plan, manifest, scan, tmp_path, [dict_step])
        text = (tmp_path / "u.py").read_text(encoding="utf-8")

        assert "user.model_dump()" in text
        assert "@validator" in text  # untouched
        assert [r.step for r in results] == [dict_step]

    def test_non_auto_fix_step_reports_error(self, tmp_path: Path) -> None:
        manifest = _manifest()
        source = SOURCE.replace(
            "def serialize(user):", "class Config:\n    pass\n\ndef serialize(user):"
        )
        nodes = NODES + [("u.py::Config", "Config", "u.py", "class", 11, 12)]
        db_path = make_index_repo(tmp_path, {"u.py": source}, nodes)
        conn = open_ro(db_path)
        scan = scan_package("pydantic", manifest, conn, tmp_path)
        plan = build_plan("pydantic", manifest, scan, conn)
        conn.close()
        config_step = _step_for(plan, "class Config")

        results = apply_fixes(plan, manifest, scan, tmp_path, [config_step])
        assert results[0].errors
        assert "not mechanically auto-fixable" in results[0].errors[0]

    def test_invalid_transform_leaves_file_unchanged(self, tmp_path: Path) -> None:
        manifest = parse_manifest(
            {
                "package": "pydantic",
                "changes": [
                    {
                        "type": "rename",
                        "old": ".dict()",
                        "new": ".for()",
                        "severity": "breaking",
                        "category": "call",
                        "match": r"\.dict\s*\(",
                        "auto_fix": True,
                    }
                ],
            }
        )
        db_path = make_index_repo(
            tmp_path,
            {"u.py": "from pydantic import BaseModel\n\ndef f(o):\n    return o.dict()\n"},
            [("u.py::u", "u", "u.py", "module", 1, 4)],
        )
        conn = open_ro(db_path)
        scan = scan_package("pydantic", manifest, conn, tmp_path)
        plan = build_plan("pydantic", manifest, scan, conn)
        conn.close()
        before = (tmp_path / "u.py").read_text(encoding="utf-8")

        results = apply_fixes(plan, manifest, scan, tmp_path)
        assert results[0].errors
        assert "invalid" in results[0].errors[0]
        assert (tmp_path / "u.py").read_text(encoding="utf-8") == before

    def test_non_python_file_is_refused(self, tmp_path: Path) -> None:
        manifest = _manifest()
        change = manifest.changes[1]
        site = UsageSite(
            change_index=1,
            neuron_id="a.txt::a",
            neuron_name="a",
            file="a.txt",
            line=1,
            snippet="obj.dict()",
        )
        scan = ScanResult(
            package="pydantic",
            imported=True,
            import_files=["a.txt"],
            usages=[ChangeUsage(change_index=1, change=change, sites=[site])],
            files_scanned=1,
        )
        plan = type(
            "Plan",
            (),
            {
                "steps": [
                    type(
                        "Step",
                        (),
                        {
                            "step_number": 1,
                            "change_index": 1,
                            "auto_fix": True,
                        },
                    )()
                ]
            },
        )()

        results = apply_fixes(plan, manifest, scan, tmp_path)  # type: ignore[arg-type]
        assert "only supports Python files" in results[0].errors[0]

    def test_unknown_step_raises(self, tmp_path: Path) -> None:
        manifest = _manifest()
        conn, scan, plan = _setup(tmp_path, manifest)
        conn.close()
        with pytest.raises(FixerError, match="Unknown step"):
            apply_fixes(plan, manifest, scan, tmp_path, [99])

    def test_no_ast_match_reports_error(self, tmp_path: Path) -> None:
        manifest = _manifest()
        change = manifest.changes[1]
        (tmp_path / "stale.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        site = UsageSite(
            change_index=1,
            neuron_id="stale.py::stale",
            neuron_name="stale",
            file="stale.py",
            line=2,
            snippet="return 1",
        )
        scan = ScanResult(
            package="pydantic",
            imported=True,
            import_files=["stale.py"],
            usages=[ChangeUsage(change_index=1, change=change, sites=[site])],
            files_scanned=1,
        )
        plan = type(
            "Plan",
            (),
            {
                "steps": [
                    type(
                        "Step",
                        (),
                        {
                            "step_number": 1,
                            "change_index": 1,
                            "auto_fix": True,
                        },
                    )()
                ]
            },
        )()
        results = apply_fixes(plan, manifest, scan, tmp_path)  # type: ignore[arg-type]
        assert "no safe AST transform" in results[0].errors[0]


def test_attribute_transform_is_scoped_to_scanned_lines(tmp_path: Path) -> None:
    manifest = parse_manifest(
        {
            "package": "pydantic",
            "changes": [
                {
                    "type": "rename",
                    "old": ".dict()",
                    "new": ".model_dump()",
                    "severity": "breaking",
                    "category": "call",
                    "match": r"\.dict\s*\(",
                    "auto_fix": True,
                }
            ],
        }
    )
    source = (
        "from pydantic import BaseModel\n"
        "\n"
        "def target(o):\n"
        "    return o.dict()\n"
        "\n"
        "def unrelated(o):\n"
        "    return o.dict()\n"
    )
    (tmp_path / "u.py").write_text(source, encoding="utf-8")
    change = manifest.changes[0]
    site = UsageSite(
        change_index=0,
        neuron_id="u.py::target",
        neuron_name="target",
        file="u.py",
        line=4,
        snippet="return o.dict()",
    )
    scan = ScanResult(
        package="pydantic",
        imported=True,
        import_files=["u.py"],
        usages=[ChangeUsage(change_index=0, change=change, sites=[site])],
        files_scanned=1,
    )
    plan = type(
        "Plan",
        (),
        {
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "step_number": 1,
                        "change_index": 0,
                        "auto_fix": True,
                    },
                )()
            ]
        },
    )()

    results = apply_fixes(plan, manifest, scan, tmp_path)  # type: ignore[arg-type]
    lines = (tmp_path / "u.py").read_text(encoding="utf-8").splitlines()

    assert lines[3] == "    return o.model_dump()"
    assert lines[6] == "    return o.dict()"  # outside the scanned site line
    assert results[0].sites_fixed == 1
    assert not results[0].errors


def test_refuses_paths_outside_repository_root(tmp_path: Path) -> None:
    manifest = _manifest()
    change = manifest.changes[1]
    site = UsageSite(
        change_index=1,
        neuron_id="outside::f",
        neuron_name="f",
        file="../outside.py",
        line=1,
        snippet="obj.dict()",
    )
    scan = ScanResult(
        package="pydantic",
        imported=True,
        import_files=["../outside.py"],
        usages=[ChangeUsage(change_index=1, change=change, sites=[site])],
        files_scanned=1,
    )
    plan = type(
        "Plan",
        (),
        {
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "step_number": 1,
                        "change_index": 1,
                        "auto_fix": True,
                    },
                )()
            ]
        },
    )()

    results = apply_fixes(plan, manifest, scan, tmp_path)  # type: ignore[arg-type]

    assert len(results) == 1
    assert "refusing to edit outside the repository root" in results[0].errors[0]
    assert not results[0].files_modified
