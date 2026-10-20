"""Unit tests for upgrade/scanner.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrofy.errors import PACKAGE_NOT_USED
from cerebrofy.upgrade.manifest import ManifestError, parse_manifest
from cerebrofy.upgrade.scanner import scan_package, scan_remaining
from tests.unit.upgrade_helpers import make_index_repo, open_ro

SOURCE = """\
from pydantic import BaseModel, validator

class UserModel(BaseModel):
    class Config:
        extra = "forbid"

    @validator("name")
    def validate_name(cls, value):
        return value

def serialize(user):
    return user.dict()

def untouched():
    return 1
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
    ("models.py::models", "models", "models.py", "module", 1, 13),
    ("models.py::UserModel", "UserModel", "models.py", "class", 3, 10),
    ("models.py::validate_name", "validate_name", "models.py", "function", 7, 9),
    ("models.py::serialize", "serialize", "models.py", "function", 11, 12),
    ("models.py::untouched", "untouched", "models.py", "function", 14, 15),
]


class TestScanPackage:
    def test_finds_all_old_api_sites(self, tmp_path: Path) -> None:
        db_path = make_index_repo(tmp_path, {"models.py": SOURCE}, NODES)
        manifest = _manifest()
        conn = open_ro(db_path)
        try:
            result = scan_package("pydantic", manifest, conn, tmp_path)
        finally:
            conn.close()

        assert result.imported is True
        assert result.package_used is True
        assert result.total_sites == 3
        by_old = {usage.change.old: usage for usage in result.usages}
        assert by_old["class Config"].sites[0].line == 4
        assert by_old[".dict()"].sites[0].neuron_id == "models.py::serialize"
        assert by_old["@validator"].sites[0].neuron_id == "models.py::validate_name"

    def test_imported_but_unused_is_package_not_used(self, tmp_path: Path) -> None:
        source = "from pydantic import BaseModel\n\nclass M(BaseModel):\n    x: int\n"
        nodes = [("m.py::m", "m", "m.py", "module", 1, 4)]
        db_path = make_index_repo(tmp_path, {"m.py": source}, nodes)
        conn = open_ro(db_path)
        try:
            result = scan_package("pydantic", _manifest(), conn, tmp_path)
        finally:
            conn.close()
        assert result.imported is True
        assert result.package_used is False
        with pytest.raises(ManifestError) as excinfo:
            result.require_used()
        assert excinfo.value.code == PACKAGE_NOT_USED
        assert "imported" in excinfo.value.message

    def test_false_positive_outside_importing_files(self, tmp_path: Path) -> None:
        files = {
            "models.py": SOURCE,
            "other.py": "def f(obj):\n    return obj.dict()\n",
        }
        nodes = NODES + [("other.py::other", "other", "other.py", "module", 1, 2)]
        db_path = make_index_repo(tmp_path, files, nodes)
        conn = open_ro(db_path)
        try:
            result = scan_package("pydantic", _manifest(), conn, tmp_path)
        finally:
            conn.close()
        dict_usage = next(u for u in result.usages if u.change.old == ".dict()")
        assert dict_usage.files == ["models.py"]

    def test_graph_edge_files_are_scanned_without_ast_import(self, tmp_path: Path) -> None:
        source = "def f(obj):\n    return obj.dict()\n"
        nodes = [("edge.py::edge", "edge", "edge.py", "module", 1, 2)]
        edges = [("edge.py::edge", "external::pydantic.BaseModel", "RUNTIME_BOUNDARY", "edge.py")]
        db_path = make_index_repo(tmp_path, {"edge.py": source}, nodes, edges)
        conn = open_ro(db_path)
        try:
            result = scan_package("pydantic", _manifest(), conn, tmp_path)
        finally:
            conn.close()
        assert result.total_sites == 1
        assert result.package_used is True

    def test_remaining_scan_ignores_import_gate(self, tmp_path: Path) -> None:
        source = "def f(obj):\n    return obj.dict()\n"
        nodes = [("left.py::left", "left", "left.py", "module", 1, 2)]
        db_path = make_index_repo(tmp_path, {"left.py": source}, nodes)
        conn = open_ro(db_path)
        try:
            result = scan_remaining(_manifest(), conn, tmp_path)
        finally:
            conn.close()
        assert result.imported is False
        assert result.total_sites == 1
