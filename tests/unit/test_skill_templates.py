"""Regression tests for GitHub issue #52: bundled skill templates must be discoverable.

OpenCode only lists a skill when its ``SKILL.md`` opens with valid YAML
frontmatter containing a ``name`` and a ``description``. A stray code fence or a
missing block silently hides the skill from the agent, so every bundled template
is checked here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "cerebrofy" / "skills" / "templates"

# Project convention: keep picker descriptions concise (OpenCode permits up to 1024).
_DESCRIPTION_MAX_LENGTH = 200
_NAME_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

# Templates that already shipped frontmatter before issue #52; they must keep it.
_LEGACY_FRONTMATTER_TEMPLATES = frozenset(
    {
        "cerebrofy-coordination",
        "cerebrofy-insights",
        "cerebrofy-intent",
        "cerebrofy-synthesize",
    }
)


def _discover_templates() -> list[Path]:
    if not _TEMPLATES_DIR.is_dir():
        return []
    return sorted(path for path in _TEMPLATES_DIR.iterdir() if path.is_dir())


_TEMPLATES = _discover_templates()


def _frontmatter(path: Path) -> dict[str, object]:
    """Return the parsed YAML frontmatter of ``path``, asserting its shape."""
    text = path.read_text(encoding="utf-8")

    assert text.startswith("---\n"), (
        f"{path} must start exactly with a '---\\n' frontmatter delimiter (found {text[:40]!r})"
    )

    lines = text.splitlines()
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    assert closing_index is not None, f"{path} frontmatter is not terminated by a second '---' line"

    parsed = yaml.safe_load("\n".join(lines[1:closing_index]))
    assert isinstance(parsed, dict), (
        f"{path} frontmatter must parse to a YAML mapping, got {type(parsed).__name__}"
    )
    return parsed


def _assert_valid_template(template_dir: Path) -> None:
    skill_path = template_dir / "SKILL.md"
    assert skill_path.is_file(), f"missing SKILL.md in template directory {template_dir}"

    metadata = _frontmatter(skill_path)

    name = metadata.get("name")
    assert isinstance(name, str) and name.strip(), (
        f"{skill_path} frontmatter 'name' must be a non-empty string"
    )
    assert name == template_dir.name, (
        f"{skill_path} frontmatter 'name' ({name!r}) must match its template "
        f"directory ({template_dir.name!r})"
    )
    assert len(name) <= 64 and _NAME_PATTERN.fullmatch(name), (
        f"{skill_path} frontmatter 'name' ({name!r}) must match OpenCode's "
        "lowercase kebab-case grammar"
    )

    description = metadata.get("description")
    assert isinstance(description, str) and description.strip(), (
        f"{skill_path} frontmatter 'description' must be a non-empty string"
    )
    assert "\n" not in description and "\r" not in description, (
        f"{skill_path} frontmatter 'description' must be a single logical line"
    )
    assert len(description) <= _DESCRIPTION_MAX_LENGTH, (
        f"{skill_path} frontmatter 'description' is {len(description)} chars "
        f"(max {_DESCRIPTION_MAX_LENGTH})"
    )


def test_templates_directory_contains_at_least_one_template() -> None:
    assert _TEMPLATES_DIR.is_dir(), f"bundled templates directory is missing: {_TEMPLATES_DIR}"
    assert _TEMPLATES, f"no skill template directories found under {_TEMPLATES_DIR}"


def test_legacy_frontmatter_templates_are_still_bundled() -> None:
    discovered = {path.name for path in _TEMPLATES}
    assert _LEGACY_FRONTMATTER_TEMPLATES <= discovered, (
        "templates that previously had frontmatter disappeared: "
        f"{sorted(_LEGACY_FRONTMATTER_TEMPLATES - discovered)}"
    )


@pytest.mark.parametrize("template_dir", _TEMPLATES, ids=lambda path: path.name)
def test_skill_template_has_valid_frontmatter(template_dir: Path) -> None:
    _assert_valid_template(template_dir)


@pytest.mark.parametrize("template_name", sorted(_LEGACY_FRONTMATTER_TEMPLATES))
def test_legacy_frontmatter_template_still_passes(template_name: str) -> None:
    _assert_valid_template(_TEMPLATES_DIR / template_name)
