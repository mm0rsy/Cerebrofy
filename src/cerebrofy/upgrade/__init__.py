"""Dependency Upgrade Navigator (Wave B idea #19).

Public surface:

* :mod:`cerebrofy.upgrade.manifest` — YAML/JSON breaking-change manifests
* :mod:`cerebrofy.upgrade.scanner` — graph + source usage detection
* :mod:`cerebrofy.upgrade.planner` — ordered, effort-scored migration plan
* :mod:`cerebrofy.upgrade.fixer` — explicit, AST-based mechanical fixes
* :mod:`cerebrofy.upgrade.validator` — post-upgrade leftover scan
"""

from __future__ import annotations

from cerebrofy.upgrade.fixer import FixResult, apply_fixes
from cerebrofy.upgrade.manifest import (
    Change,
    Manifest,
    ManifestError,
    find_manifest,
    load_manifest_file,
    parse_manifest,
)
from cerebrofy.upgrade.planner import UpgradePlan, build_plan, render_markdown
from cerebrofy.upgrade.scanner import ScanResult, scan_package
from cerebrofy.upgrade.validator import ValidationResult, validate_upgrade

__all__ = [
    "Change",
    "FixResult",
    "Manifest",
    "ManifestError",
    "ScanResult",
    "UpgradePlan",
    "ValidationResult",
    "apply_fixes",
    "build_plan",
    "find_manifest",
    "load_manifest_file",
    "parse_manifest",
    "render_markdown",
    "scan_package",
    "validate_upgrade",
]
