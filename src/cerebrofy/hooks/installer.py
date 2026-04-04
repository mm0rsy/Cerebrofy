"""Git hook installer with idempotency sentinel support."""

from __future__ import annotations

import os
from pathlib import Path

# FR-020: sentinel format — supersedes earlier cerebrofy-hook-start/end format
HOOK_MARKER_START = "# BEGIN cerebrofy"
HOOK_MARKER_END = "# END cerebrofy"

# Version 1 = warn-only (Phase 1). Version 2 = hard-block (Phase 3 upgrade).
HOOK_SCRIPT_BLOCK = """\
{marker_start}
# cerebrofy-hook-version: 1
cerebrofy validate --hook {{hook_name}}
{marker_end}
""".format(marker_start=HOOK_MARKER_START, marker_end=HOOK_MARKER_END)


def has_cerebrofy_marker(hook_path: Path) -> bool:
    """Return True if the hook file already contains the cerebrofy sentinel."""
    if not hook_path.exists():
        return False
    return HOOK_MARKER_START in hook_path.read_text(encoding="utf-8")


def create_hook_file(hook_path: Path, hook_name: str) -> None:
    """Create a new executable hook file with the cerebrofy block."""
    block = HOOK_SCRIPT_BLOCK.format(hook_name=hook_name)
    hook_path.write_text(f"#!/bin/sh\n{block}", encoding="utf-8")
    try:
        os.chmod(hook_path, 0o755)
    except (NotImplementedError, OSError):
        pass  # Windows — executability handled by git's hook runner


def append_to_hook(hook_path: Path, hook_name: str) -> str:
    """Append the cerebrofy block to an existing hook file. Returns a warning string."""
    block = HOOK_SCRIPT_BLOCK.format(hook_name=hook_name)
    existing = hook_path.read_text(encoding="utf-8")
    hook_path.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
    return f"Warning: Pre-existing hook at {hook_path} — appending Cerebrofy call."


def install_hooks(root: Path) -> list[str]:
    """Install cerebrofy pre-push and post-merge hooks. Returns any warning messages."""
    hooks_dir = root / ".git" / "hooks"
    warnings: list[str] = []
    for hook_name in ("pre-push", "post-merge"):
        hook_path = hooks_dir / hook_name
        if not hook_path.exists():
            create_hook_file(hook_path, hook_name)
        elif not has_cerebrofy_marker(hook_path):
            warnings.append(append_to_hook(hook_path, hook_name))
        # else: marker already present — skip (idempotent)
    return warnings


def upgrade_to_hard_block(hook_path: Path) -> None:
    """Upgrade the cerebrofy pre-push hook from warn-only (v1) to hard-block (v2).

    Replaces version marker and adds explicit exit-code propagation.
    Emits a warning if sentinels are absent (manually edited hook).
    """
    if not hook_path.exists():
        return
    content = hook_path.read_text(encoding="utf-8")
    if HOOK_MARKER_START not in content or HOOK_MARKER_END not in content:
        import click
        click.echo(
            "Warning: Git hook not managed by Cerebrofy — manual upgrade to hard-block required.",
            err=True,
        )
        return
    # Replace version marker and add exit-code propagation
    content = content.replace(
        "# cerebrofy-hook-version: 1", "# cerebrofy-hook-version: 2"
    )
    # Replace warn-only call with hard-block call
    content = content.replace(
        "cerebrofy validate --hook pre-push\n",
        "cerebrofy validate --hook pre-push\nexit_code=$?\nif [ $exit_code -ne 0 ]; then exit 1; fi\n",
    )
    hook_path.write_text(content, encoding="utf-8")


def downgrade_to_warn_only(hook_path: Path) -> None:
    """Downgrade the cerebrofy pre-push hook from hard-block (v2) to warn-only (v1).

    Inverse of upgrade_to_hard_block.
    """
    if not hook_path.exists():
        return
    content = hook_path.read_text(encoding="utf-8")
    if HOOK_MARKER_START not in content or HOOK_MARKER_END not in content:
        return
    content = content.replace(
        "# cerebrofy-hook-version: 2", "# cerebrofy-hook-version: 1"
    )
    content = content.replace(
        "cerebrofy validate --hook pre-push\nexit_code=$?\nif [ $exit_code -ne 0 ]; then exit 1; fi\n",
        "cerebrofy validate --hook pre-push\n",
    )
    hook_path.write_text(content, encoding="utf-8")


def add_gitignore_entry(repo_root: Path) -> None:
    """Append .cerebrofy/db/ to .gitignore if not already present (FR-019)."""
    entry = ".cerebrofy/db/"
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if entry in content:
            return
        gitignore.write_text(content.rstrip("\n") + f"\n{entry}\n", encoding="utf-8")
    else:
        gitignore.write_text(f"{entry}\n", encoding="utf-8")
