"""IgnoreRuleSet — merges .cerebrofy-ignore and .gitignore via pathspec."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pathspec as _pathspec

DEFAULT_IGNORE_CONTENT = """\
# Cerebrofy default ignore list — edit to customize
node_modules/
__pycache__/
.git/
dist/
build/
out/
vendor/
.venv/
venv/
*.min.js
*.min.css
*.map
*.lock
*.pyc
*.egg-info/
coverage/
.nyc_output/
"""


@dataclass
class IgnoreRuleSet:
    """Combined ignore rules from .cerebrofy-ignore and .gitignore."""

    cerebrofy_lines: list[str] = field(default_factory=list)
    git_lines: list[str] = field(default_factory=list)
    # Compiled once in __post_init__; excluded from constructor, repr, and equality.
    _spec: Optional[_pathspec.PathSpec] = field(init=False, repr=False, compare=False,
                                                default=None)

    def __post_init__(self) -> None:
        all_lines = self.cerebrofy_lines + self.git_lines
        self._spec = (
            _pathspec.PathSpec.from_lines("gitwildmatch", all_lines) if all_lines else None
        )

    @classmethod
    def from_directory(cls, root: Path) -> IgnoreRuleSet:
        """Read .cerebrofy-ignore and .gitignore from root (either may be absent)."""
        def read_lines(path: Path) -> list[str]:
            if path.exists():
                return path.read_text(encoding="utf-8").splitlines()
            return []

        return cls(
            cerebrofy_lines=read_lines(root / ".cerebrofy-ignore"),
            git_lines=read_lines(root / ".gitignore"),
        )

    def matches(self, path: str) -> bool:
        """Return True if path matches any rule in either ignore set."""
        return self._spec.match_file(path) if self._spec else False
