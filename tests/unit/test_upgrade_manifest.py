"""Unit tests for upgrade/manifest.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrofy.errors import MANIFEST_NOT_FOUND, VERSION_NOT_FOUND
from cerebrofy.upgrade.manifest import (
    ManifestError,
    find_manifest,
    load_manifest_file,
    parse_manifest,
    version_satisfies,
)


class TestParseManifest:
    def test_parses_documented_yaml_shape(self, tmp_path: Path) -> None:
        path = tmp_path / "m.yaml"
        path.write_text(
            "package: demo\n"
            "from_version: '>=1.0,<2.0'\n"
            "to_version: '>=2.0'\n"
            "changes:\n"
            "  - type: rename\n"
            "    old: .dict()\n"
            "    new: .model_dump()\n"
            "    severity: breaking\n"
            "  - type: removed\n"
            "    old: demo.old_api\n"
            "    new: demo.new_api\n"
            "    severity: deprecated\n",
            encoding="utf-8",
        )
        manifest = load_manifest_file(path)
        assert manifest.package == "demo"
        assert len(manifest.changes) == 2
        assert manifest.changes[0].category == "call"
        assert manifest.changes[0].auto_fix is True
        assert manifest.changes[1].category == "other"
        assert manifest.changes[1].auto_fix is False

    def test_bare_list_uses_overrides(self) -> None:
        manifest = parse_manifest(
            [
                {
                    "type": "rename",
                    "old_api": "old_name()",
                    "new_api": "new_name()",
                    "severity": "breaking",
                }
            ],
            package_override="demo",
            from_override="1",
            to_override="2",
        )
        assert manifest.package == "demo"
        assert manifest.changes[0].old == "old_name()"

    def test_invalid_regex_rejected(self) -> None:
        with pytest.raises(ManifestError, match="bad regex"):
            parse_manifest(
                {
                    "package": "demo",
                    "changes": [
                        {
                            "type": "rename",
                            "old": "old",
                            "new": "new",
                            "severity": "breaking",
                            "match": "[",
                        }
                    ],
                }
            )

    def test_missing_changes_rejected(self) -> None:
        with pytest.raises(ManifestError, match="'changes' must be a list"):
            parse_manifest({"package": "demo"})

    def test_explicit_auto_fix_opt_out(self) -> None:
        manifest = parse_manifest(
            {
                "package": "demo",
                "changes": [
                    {
                        "type": "rename",
                        "old": ".dict()",
                        "new": ".model_dump()",
                        "severity": "breaking",
                        "auto_fix": False,
                    }
                ],
            }
        )
        assert manifest.changes[0].auto_fix is False


class TestVersionSatisfies:
    @pytest.mark.parametrize(
        ("constraint", "version", "expected"),
        [
            (">=1.0,<2.0", "1.10.0", True),
            (">=1.0,<2.0", "v1", True),
            (">=1.0,<2.0", "2.0.0", False),
            (">=2.0", "2.0.0", True),
            (">=2.0", "1.9.9", False),
            ("==2.3.1", "2.3.1", True),
            ("", "9.9", True),
            (">=2.0", None, True),
        ],
    )
    def test_constraints(self, constraint: str, version: str | None, expected: bool) -> None:
        assert version_satisfies(constraint, version) is expected


class TestFindManifest:
    def test_finds_bundled_pydantic(self) -> None:
        manifest = find_manifest("pydantic", "1.10", "2.0")
        assert manifest.package == "pydantic"
        assert any(change.old == ".dict()" for change in manifest.changes)

    def test_finds_bundled_requests(self) -> None:
        manifest = find_manifest("requests", "2.31", "3.0")
        assert manifest.package == "requests"

    def test_unknown_package_raises_not_found(self) -> None:
        with pytest.raises(ManifestError) as excinfo:
            find_manifest("definitely-not-a-package")
        assert excinfo.value.code == MANIFEST_NOT_FOUND
        assert "--manifest" in excinfo.value.message

    def test_known_package_wrong_versions_raises_version_not_found(self) -> None:
        with pytest.raises(ManifestError) as excinfo:
            find_manifest("pydantic", "2.0", "2.5")
        assert excinfo.value.code == VERSION_NOT_FOUND

    def test_explicit_manifest_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "custom.json"
        path.write_text(
            '{"package": "demo", "from_version": "1", "to_version": "2", '
            '"changes": [{"type": "rename", "old": "a()", "new": "b()", '
            '"severity": "breaking"}]}',
            encoding="utf-8",
        )
        manifest = find_manifest("demo", "1", "2", manifest_path=path)
        assert manifest.changes[0].old == "a()"

    def test_explicit_manifest_package_mismatch(self, tmp_path: Path) -> None:
        path = tmp_path / "custom.yaml"
        path.write_text(
            "package: other\nchanges:\n  - type: rename\n    old: a()\n    new: b()\n"
            "    severity: breaking\n",
            encoding="utf-8",
        )
        with pytest.raises(ManifestError, match="not 'demo'"):
            find_manifest("demo", manifest_path=path)
