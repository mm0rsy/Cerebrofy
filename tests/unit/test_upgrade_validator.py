"""Unit tests for upgrade/validator.py."""

from __future__ import annotations

from pathlib import Path

from cerebrofy.upgrade.manifest import parse_manifest
from cerebrofy.upgrade.validator import validate_upgrade
from tests.unit.upgrade_helpers import make_index_repo, open_ro

SOURCE = """\
from pydantic import BaseModel

class User(BaseModel):
    name: str

def serialize(user):
    return user.dict()
"""


def _manifest() -> object:
    return parse_manifest(
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
    ("u.py::u", "u", "u.py", "module", 1, 7),
    ("u.py::serialize", "serialize", "u.py", "function", 6, 7),
]


class TestValidateUpgrade:
    def test_fails_with_remaining_sites_by_file_line(self, tmp_path: Path) -> None:
        db_path = make_index_repo(tmp_path, {"u.py": SOURCE}, NODES)
        conn = open_ro(db_path)
        try:
            result = validate_upgrade(_manifest(), conn, tmp_path)
        finally:
            conn.close()

        assert result.passed is False
        assert result.remaining[0].file == "u.py"
        assert result.remaining[0].line == 7
        assert result.remaining[0].old_api == ".dict()"
        markdown = result.to_markdown()
        assert "FAIL" in markdown
        assert "u.py:7" in markdown

    def test_passes_after_patterns_removed(self, tmp_path: Path) -> None:
        fixed = SOURCE.replace("user.dict()", "user.model_dump()")
        db_path = make_index_repo(tmp_path, {"u.py": fixed}, NODES)
        conn = open_ro(db_path)
        try:
            result = validate_upgrade(_manifest(), conn, tmp_path)
        finally:
            conn.close()
        assert result.passed is True
        assert result.remaining == []
        assert "PASS" in result.to_markdown()

    def test_finds_leftover_after_import_removed(self, tmp_path: Path) -> None:
        source = "def f(obj):\n    return obj.dict()\n"
        nodes = [("left.py::left", "left", "left.py", "module", 1, 2)]
        db_path = make_index_repo(tmp_path, {"left.py": source}, nodes)
        conn = open_ro(db_path)
        try:
            result = validate_upgrade(_manifest(), conn, tmp_path)
        finally:
            conn.close()
        assert result.passed is False
        assert len(result.remaining) == 1
