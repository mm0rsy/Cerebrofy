"""Post-upgrade validation: confirm that no old API patterns remain.

Validation rescans every indexed Python file *without* an import gate, so an
old pattern is still caught when the package import was renamed or removed but
the call site was missed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.upgrade.manifest import Manifest
from cerebrofy.upgrade.scanner import scan_remaining


@dataclass(frozen=True)
class RemainingSite:
    """One old API pattern still present after the upgrade."""

    change_index: int
    old_api: str
    new_api: str
    file: str
    line: int
    neuron_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "change_index": self.change_index,
            "old_api": self.old_api,
            "new_api": self.new_api,
            "file": self.file,
            "line": self.line,
            "neuron_id": self.neuron_id,
        }


@dataclass
class ValidationResult:
    """Result of a post-upgrade scan."""

    package: str
    passed: bool
    files_scanned: int
    checked_changes: int
    remaining: list[RemainingSite] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "package": self.package,
            "passed": self.passed,
            "status": "PASS" if self.passed else "FAIL",
            "files_scanned": self.files_scanned,
            "checked_changes": self.checked_changes,
            "remaining": [site.to_dict() for site in self.remaining],
        }

    def to_markdown(self) -> str:
        if self.passed:
            return (
                f"✅ **PASS** — no remaining `{self.package}` upgrade patterns "
                f"across {self.files_scanned} indexed Python file(s)."
            )
        lines = [
            f"❌ **FAIL** — {len(self.remaining)} remaining `{self.package}` pattern(s):",
            "",
        ]
        for site in self.remaining:
            lines.append(
                f"- `{site.file}:{site.line}` — `{site.old_api}` → `{site.new_api}` "
                f"(`{site.neuron_id}`)"
            )
        return "\n".join(lines)


def validate_upgrade(
    manifest: Manifest,
    conn: sqlite3.Connection,
    root: Path,
) -> ValidationResult:
    """Rescan the index for every old API pattern in *manifest*."""
    scan = scan_remaining(manifest, conn, root)
    remaining: list[RemainingSite] = []
    for usage in scan.usages:
        for site in usage.sites:
            remaining.append(
                RemainingSite(
                    change_index=usage.change_index,
                    old_api=usage.change.old,
                    new_api=usage.change.new,
                    file=site.file,
                    line=site.line,
                    neuron_id=site.neuron_id,
                )
            )
    remaining.sort(key=lambda s: (s.file, s.line, s.change_index))
    return ValidationResult(
        package=manifest.package,
        passed=not remaining,
        files_scanned=scan.files_scanned,
        checked_changes=len(manifest.changes),
        remaining=remaining,
    )
