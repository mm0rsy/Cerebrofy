"""CLI tests for `cerebrofy upgrade`."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cerebrofy.cli import main
from tests.unit.upgrade_helpers import make_index_repo

SOURCE = """\
from pydantic import BaseModel, validator

class User(BaseModel):
    class Config:
        extra = "forbid"

    @validator("name")
    def check(cls, value):
        return value

def serialize(user):
    return user.dict()
"""

NODES = [
    ("u.py::u", "u", "u.py", "module", 1, 12),
    ("u.py::User", "User", "u.py", "class", 3, 9),
    ("u.py::check", "check", "u.py", "function", 7, 9),
    ("u.py::serialize", "serialize", "u.py", "function", 11, 12),
]

CUSTOM_MANIFEST = """\
package: pydantic
from_version: ">=1,<2"
to_version: ">=2"
changes:
  - type: rename
    old: ".dict()"
    new: ".model_dump()"
    severity: breaking
    category: call
    match: '\\.dict\\s*\\('
    auto_fix: true
"""


def _repo(tmp_path: Path) -> None:
    make_index_repo(tmp_path, {"u.py": SOURCE}, NODES)


class TestUpgradeCli:
    def test_plans_builtin_manifest(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        result = CliRunner().invoke(main, ["upgrade", "pydantic", "--from", "1.10", "--to", "2.0"])
        assert result.exit_code == 0, result.output
        assert "Upgrade Navigator: pydantic" in result.output
        assert "Step-by-Step Migration Plan" in result.output

    def test_json_format_matches_schema(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        result = CliRunner().invoke(
            main,
            ["upgrade", "pydantic", "--from", "1.10", "--to", "2.0", "--format", "json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["package"] == "pydantic"
        assert payload["risk"] in {"LOW", "MEDIUM", "HIGH"}
        assert "steps" in payload and payload["steps"]
        assert "breaking_changes" in payload

    def test_no_index_error(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(main, ["upgrade", "pydantic"])
        assert result.exit_code == 1
        assert "[NO_INDEX]" in result.output

    def test_manifest_not_found_error(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        result = CliRunner().invoke(main, ["upgrade", "unknown-package"])
        assert result.exit_code == 1
        assert "[MANIFEST_NOT_FOUND]" in result.output

    def test_version_not_found_error(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        result = CliRunner().invoke(main, ["upgrade", "pydantic", "--from", "2.0", "--to", "2.5"])
        assert result.exit_code == 1
        assert "[VERSION_NOT_FOUND]" in result.output

    def test_auto_fix_with_explicit_step(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        manifest = tmp_path / "custom.yaml"
        manifest.write_text(CUSTOM_MANIFEST, encoding="utf-8")

        result = CliRunner().invoke(
            main,
            [
                "upgrade",
                "pydantic",
                "--manifest",
                str(manifest),
                "--auto-fix",
                "--step",
                "1",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Auto-fix Results" in result.output
        assert "user.model_dump()" in (tmp_path / "u.py").read_text(encoding="utf-8")

    def test_malformed_manifest_yaml_is_reported(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        bad = tmp_path / "bad.yaml"
        bad.write_text("package: pydantic\nchanges: [unclosed\n", encoding="utf-8")

        result = CliRunner().invoke(main, ["upgrade", "pydantic", "--manifest", str(bad)])

        assert result.exit_code == 1
        assert "[INVALID_MANIFEST]" in result.output
        assert "Invalid manifest" in result.output

    def test_manifest_dir_is_searched_before_bundled(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        custom = CUSTOM_MANIFEST.replace('new: ".model_dump()"', 'new: ".as_dict()"')
        (manifest_dir / "pydantic-custom.yaml").write_text(custom, encoding="utf-8")

        result = CliRunner().invoke(
            main,
            [
                "upgrade",
                "pydantic",
                "--from",
                "1.10",
                "--to",
                "2.0",
                "--manifest-dir",
                str(manifest_dir),
            ],
        )

        assert result.exit_code == 0, result.output
        assert ".as_dict()" in result.output
        assert ".model_dump()" not in result.output

    def test_validate_fails_then_passes(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        manifest = tmp_path / "custom.yaml"
        manifest.write_text(CUSTOM_MANIFEST, encoding="utf-8")
        runner = CliRunner()
        args = ["upgrade", "pydantic", "--manifest", str(manifest), "--validate"]

        failing = runner.invoke(main, args)
        assert failing.exit_code == 1
        assert "FAIL" in failing.output
        assert "u.py:12" in failing.output

        fixed = SOURCE.replace("user.dict()", "user.model_dump()")
        (tmp_path / "u.py").write_text(fixed, encoding="utf-8")
        passing = runner.invoke(main, args)
        assert passing.exit_code == 0, passing.output
        assert "PASS" in passing.output

    def test_package_option_alias(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        result = CliRunner().invoke(
            main, ["upgrade", "--package", "pydantic", "--from", "1.10", "--to", "2.0"]
        )
        assert result.exit_code == 0, result.output
        assert "Upgrade Navigator: pydantic" in result.output

    def test_missing_package_argument(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.chdir(tmp_path)
        _repo(tmp_path)
        result = CliRunner().invoke(main, ["upgrade"])
        assert result.exit_code == 1
        assert "Provide a PACKAGE" in result.output
