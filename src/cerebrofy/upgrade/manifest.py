"""Breaking-change manifest parsing and discovery.

A manifest is a small YAML/JSON document describing the API changes between two
versions of a dependency::

    package: pydantic
    from_version: ">=1.0,<2.0"
    to_version: ">=2.0"
    changes:
      - type: rename
        old: ".dict()"
        new: ".model_dump()"
        severity: breaking

The bundled manifests under ``manifests/`` are *curated*, not exhaustive. They
cover the mechanical, high-frequency changes that Cerebrofy can map safely onto
an indexed graph; always pair them with the library's own migration guide.

Optional fields (an extension used by the fixer) keep the transform precise::

    match: '\\.dict\\s*\\(\\s*\\)'   # explicit regex for detection
    replacement: ".model_dump()"     # explicit textual replacement
    category: call                   # base | call | validator | other
    auto_fix: true                   # manifest-level opt-out switch

The module is offline by design — it never contacts PyPI or GitHub. Automatic
changelog fetching is deliberately deferred (see ``docs/upgrade.md``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cerebrofy.errors import (
    MANIFEST_NOT_FOUND,
    VERSION_NOT_FOUND,
    CerebrofyError,
)

_VALID_TYPES = frozenset({"rename", "removed", "changed"})
_VALID_SEVERITIES = frozenset({"breaking", "deprecated"})
_VALID_CATEGORIES = frozenset({"base", "call", "validator", "other"})


class ManifestError(CerebrofyError):
    """A manifest is missing, malformed, or does not cover the version pair."""

    code: str = MANIFEST_NOT_FOUND


@dataclass(frozen=True)
class Change:
    """One API change in a manifest."""

    type: str
    old: str
    new: str
    severity: str
    category: str
    match: str | None
    replacement: str | None
    auto_fix: bool

    def compiled_pattern(self) -> re.Pattern[str]:
        """Return the detection regex for this change (compiled, cached by re)."""
        pattern = self.match if self.match is not None else derive_pattern(self.old, self.category)
        return re.compile(pattern)

    def to_dict(self) -> dict[str, str]:
        """Serialise the user-facing fields (no internal fixer metadata)."""
        return {
            "type": self.type,
            "old": self.old,
            "new": self.new,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class Manifest:
    """A parsed breaking-change manifest."""

    package: str
    from_version: str
    to_version: str
    changes: tuple[Change, ...]
    source: str
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation (used by tests and diagnostics)."""
        return {
            "package": self.package,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "source": self.source,
            "notes": self.notes,
            "changes": [c.to_dict() for c in self.changes],
        }


# ---------------------------------------------------------------------------
# Pattern derivation
# ---------------------------------------------------------------------------

def derive_category(old: str, new: str = "") -> str:
    """Classify a change as base/call/validator/other when not explicit."""
    lowered = old.strip().lower()
    if lowered.startswith("class ") or "base model" in lowered or lowered == "class config":
        return "base"
    if "validator" in lowered or lowered.startswith("@"):
        return "validator"
    if lowered.startswith(".") or "(" in lowered:
        return "call"
    return "other"


def derive_pattern(old: str, category: str) -> str:
    """Build a conservative default regex from an ``old`` API string.

    The heuristic is intentionally narrow: manifests that need something more
    precise should provide an explicit ``match`` regex.
    """
    stripped = old.strip()
    if category == "base" or stripped.lower().startswith("class "):
        name = stripped.split()[-1]
        return rf"^\s*class\s+{re.escape(name)}\b"
    if stripped.startswith("@"):
        return rf"@{re.escape(stripped[1:])}\b"
    if stripped.startswith("."):
        # ".dict()" -> \.dict\s*\(
        name = stripped[1:].split("(")[0].strip()
        if "(" in stripped:
            return rf"\.{re.escape(name)}\s*\("
        return rf"\.{re.escape(name)}\b"
    if "(" in stripped:
        name = stripped.split("(")[0].rsplit(".", 1)[-1].strip()
        return rf"\b{re.escape(name)}\s*\("
    return rf"\b{re.escape(stripped)}\b"


def _derive_auto_fix(change_type: str, old: str, new: str, category: str) -> bool:
    """Default opt-in only for transforms the AST fixer can apply safely."""
    if change_type == "changed":
        return False
    if new.endswith("...") or "..." in new:
        return False
    if category == "base":
        return False
    if old.strip().startswith(".") and "(" in old:
        return True
    if old.strip().startswith("@"):
        return True
    return False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _normalise_package(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(".", "_")


def _require_str(mapping: dict[str, Any], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"Invalid manifest {where}: '{key}' must be a non-empty string.")
    return value.strip()


def _coerce_change(raw: object, where: str) -> Change:
    if not isinstance(raw, dict):
        raise ManifestError(f"Invalid manifest {where}: each change must be a mapping.")
    raw_map: dict[str, Any] = raw
    change_type = str(raw_map.get("type") or "changed").strip().lower()
    if change_type not in _VALID_TYPES:
        raise ManifestError(
            f"Invalid manifest {where}: change type must be one of "
            f"{', '.join(sorted(_VALID_TYPES))}."
        )
    # Accept both the documented old/new spelling and the "API diff" spelling.
    old_raw = raw_map.get("old", raw_map.get("old_api"))
    new_raw = raw_map.get("new", raw_map.get("new_api"))
    if not isinstance(old_raw, str) or not old_raw.strip():
        raise ManifestError(f"Invalid manifest {where}: change 'old' must be a non-empty string.")
    if not isinstance(new_raw, str) or not new_raw.strip():
        raise ManifestError(f"Invalid manifest {where}: change 'new' must be a non-empty string.")
    old = old_raw.strip()
    new = new_raw.strip()
    severity = str(raw_map.get("severity") or "breaking").strip().lower()
    if severity not in _VALID_SEVERITIES:
        raise ManifestError(
            f"Invalid manifest {where}: severity must be one of "
            f"{', '.join(sorted(_VALID_SEVERITIES))}."
        )
    category = str(raw_map.get("category") or derive_category(old, new)).strip().lower()
    if category not in _VALID_CATEGORIES:
        raise ManifestError(
            f"Invalid manifest {where}: category must be one of "
            f"{', '.join(sorted(_VALID_CATEGORIES))}."
        )
    match = raw_map.get("match")
    if match is not None:
        if not isinstance(match, str):
            raise ManifestError(f"Invalid manifest {where}: 'match' must be a regex string.")
        try:
            re.compile(match)
        except re.error as exc:
            raise ManifestError(f"Invalid manifest {where}: bad regex {match!r}: {exc}") from exc
    replacement = raw_map.get("replacement")
    if replacement is not None and not isinstance(replacement, str):
        raise ManifestError(f"Invalid manifest {where}: 'replacement' must be a string.")
    auto_fix_raw = raw_map.get("auto_fix")
    if auto_fix_raw is None:
        auto_fix = _derive_auto_fix(change_type, old, new, category)
    else:
        auto_fix = bool(auto_fix_raw)
    return Change(
        type=change_type,
        old=old,
        new=new,
        severity=severity,
        category=category,
        match=match,
        replacement=replacement,
        auto_fix=auto_fix,
    )


def parse_manifest(
    data: object,
    *,
    source: str = "<memory>",
    package_override: str | None = None,
    from_override: str | None = None,
    to_override: str | None = None,
) -> Manifest:
    """Parse a manifest mapping (or a bare list of change mappings)."""
    notes: str | None = None
    if isinstance(data, list):
        changes_raw: list[object] = data
        package = package_override or ""
        from_version = from_override or ""
        to_version = to_override or ""
    elif isinstance(data, dict):
        raw_map: dict[str, Any] = data
        package_val = raw_map.get("package", package_override)
        if not isinstance(package_val, str) or not package_val.strip():
            raise ManifestError(
                f"Invalid manifest {source}: 'package' is required "
                "(pass a package name alongside a bare --diff list)."
            )
        package = package_val.strip()
        from_version = str(raw_map.get("from_version", from_override or "")).strip()
        to_version = str(raw_map.get("to_version", to_override or "")).strip()
        changes_raw_obj = raw_map.get("changes")
        if not isinstance(changes_raw_obj, list):
            raise ManifestError(f"Invalid manifest {source}: 'changes' must be a list.")
        changes_raw = changes_raw_obj
        raw_notes = raw_map.get("notes")
        notes = raw_notes.strip() if isinstance(raw_notes, str) else None
    else:
        raise ManifestError(f"Invalid manifest {source}: top-level mapping or list expected.")

    if not changes_raw:
        raise ManifestError(f"Invalid manifest {source}: 'changes' must not be empty.")
    changes = tuple(
        _coerce_change(item, f"{source} (change {index + 1})")
        for index, item in enumerate(changes_raw)
    )
    return Manifest(
        package=package,
        from_version=from_version,
        to_version=to_version,
        changes=changes,
        source=source,
        notes=notes,
    )


def load_manifest_file(
    path: Path,
    *,
    package_override: str | None = None,
    from_override: str | None = None,
    to_override: str | None = None,
) -> Manifest:
    """Load a YAML or JSON manifest from *path* (JSON is detected by content)."""
    if not path.exists() or not path.is_file():
        raise ManifestError(
            f"Manifest not found at {path}. Provide a YAML/JSON manifest via "
            "--manifest/--diff or add one with --manifest-dir."
        )
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    try:
        if path.suffix.lower() == ".json" or stripped.startswith(("{", "[")):
            data: object = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ManifestError(f"Invalid manifest {path}: {exc}") from exc
    return parse_manifest(
        data,
        source=str(path),
        package_override=package_override,
        from_override=from_override,
        to_override=to_override,
    )


def load_manifests_from_dir(directory: Path) -> list[Manifest]:
    """Load every ``*.yaml``/``*.yml``/``*.json`` manifest under *directory*."""
    if not directory.is_dir():
        return []
    manifests: list[Manifest] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in (".yaml", ".yml", ".json"):
            continue
        manifests.append(load_manifest_file(path))
    return manifests


def builtin_manifest_dir() -> Path:
    """Return the directory holding Cerebrofy's curated manifests."""
    return Path(__file__).resolve().parent / "manifests"


# ---------------------------------------------------------------------------
# Version matching (offline, constraint-prefix heuristic)
# ---------------------------------------------------------------------------

def _version_tuple(version: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", version)
    if not nums:
        # Version labels without digits (e.g. "v1" has a digit, "latest" does
        # not) cannot be compared — treat them as matching everything.
        return ()
    return tuple(int(n) for n in nums[:3])


def _pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    width = max(len(a), len(b), 1)
    return a + (0,) * (width - len(a)), b + (0,) * (width - len(b))


def version_satisfies(constraint: str, version: str | None) -> bool:
    """Return True when *version* satisfies the (simple) *constraint* string.

    Supports comma-separated ``>=``, ``<=``, ``>``, ``<``, ``==``, ``!=``
    clauses and bare versions (treated as ``==`` on the numeric prefix).
    Unknown/non-numeric versions match everything — manifests are advisory.
    """
    if not constraint or not version:
        return True
    actual = _version_tuple(version)
    if not actual:
        return True
    for clause in (part.strip() for part in constraint.split(",")):
        if not clause:
            continue
        match = re.match(r"^(>=|<=|==|!=|>|<)?\s*(.+)$", clause)
        if match is None:
            continue
        op = match.group(1) or "=="
        expected = _version_tuple(match.group(2))
        if not expected:
            continue
        left, right = _pad(actual, expected)
        if op == ">=" and not left >= right:
            return False
        if op == "<=" and not left <= right:
            return False
        if op == ">" and not left > right:
            return False
        if op == "<" and not left < right:
            return False
        if op == "==" and not left[: len(right)] == right:
            return False
        if op == "!=" and left[: len(right)] == right:
            return False
    return True


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_manifest(
    package: str,
    from_version: str | None = None,
    to_version: str | None = None,
    *,
    manifest_path: Path | None = None,
    manifest_dir: Path | None = None,
    extra_dirs: tuple[Path, ...] = (),
) -> Manifest:
    """Resolve the best manifest for *package* and the requested version pair.

    Search order: explicit ``manifest_path`` → ``manifest_dir`` → ``extra_dirs``
    → bundled manifests. Raises :class:`ManifestError` with
    ``MANIFEST_NOT_FOUND`` (unknown package) or ``VERSION_NOT_FOUND`` (package
    known but no manifest covers the requested pair).
    """
    if manifest_path is not None:
        manifest = load_manifest_file(
            manifest_path,
            package_override=package,
            from_override=from_version,
            to_override=to_version,
        )
        if _normalise_package(manifest.package) != _normalise_package(package):
            raise ManifestError(
                f"Manifest {manifest_path} is for package '{manifest.package}', "
                f"not '{package}'."
            )
        return manifest

    directories: list[Path] = []
    if manifest_dir is not None:
        directories.append(manifest_dir)
    directories.extend(extra_dirs)
    directories.append(builtin_manifest_dir())

    candidates: list[Manifest] = []
    for directory in directories:
        candidates.extend(load_manifests_from_dir(directory))

    matching_package = [
        m for m in candidates if _normalise_package(m.package) == _normalise_package(package)
    ]
    if not matching_package:
        raise ManifestError(
            f"No breaking-change manifest found for package '{package}'. "
            "Pass a curated file with --manifest/--diff, or add one with "
            "--manifest-dir. (Automatic PyPI changelog fetching is not enabled.)"
        )

    matched_versions = [
        m
        for m in matching_package
        if version_satisfies(m.from_version, from_version)
        and version_satisfies(m.to_version, to_version)
    ]
    if not matched_versions:
        available = ", ".join(
            f"{m.from_version or '?'} -> {m.to_version or '?'}" for m in matching_package
        )
        raise ManifestError(
            f"No manifest for '{package}' covers "
            f"{from_version or 'any'} -> {to_version or 'any'}. "
            f"Available ranges: {available}. Pass --manifest/--diff for a custom diff.",
            code=VERSION_NOT_FOUND,
        )
    return matched_versions[0]
