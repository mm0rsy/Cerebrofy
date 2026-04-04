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


def _generate_post_merge_script(map_md_path: str, db_path: str) -> str:
    """Return the shell script body for the cerebrofy post-merge hook.

    map_md_path and db_path are injected as Python string literals at generation time
    (resolved from repo_root at install time — the shell script cannot read config.yaml).
    Script reads state_hash from cerebrofy_map.md; queries DB meta table via sqlite3.
    Always exits 0 (WARN-only, never blocks).
    """
    map_md_literal = repr(map_md_path)
    db_literal = repr(db_path)
    return f"""\
{HOOK_MARKER_START}
# cerebrofy-hook-version: 1
python3 << 'CEREBROFY_PM_CHECK'
import re, sqlite3, sys
MAP_MD = {map_md_literal}
DB_PATH = {db_literal}
try:
    content = open(MAP_MD, encoding='utf-8').read()
    m = re.search(r'\\*\\*State Hash\\*\\*: `([a-f0-9]+)`', content)
    remote_hash = m.group(1) if m else ''
except Exception:
    sys.exit(0)
try:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM meta WHERE key='state_hash'").fetchone()
    local_hash = row[0] if row else ''
    conn.close()
except Exception:
    sys.exit(0)
if remote_hash and local_hash and remote_hash != local_hash:
    print("Cerebrofy: Remote index state differs. Run 'cerebrofy build' to resync.", file=sys.stderr)
CEREBROFY_PM_CHECK
{HOOK_MARKER_END}
"""


def install_hooks(root: Path, config: object = None) -> list[str]:
    """Install cerebrofy pre-push and post-merge hooks. Returns any warning messages.

    config is accepted for forward compatibility but paths are derived from root.
    """
    hooks_dir = root / ".git" / "hooks"
    warnings: list[str] = []

    # Pre-push hook: calls cerebrofy validate (warn-only by default)
    pre_push = hooks_dir / "pre-push"
    if not pre_push.exists():
        create_hook_file(pre_push, "pre-push")
    elif not has_cerebrofy_marker(pre_push):
        warnings.append(append_to_hook(pre_push, "pre-push"))

    # Post-merge hook: state_hash sync check (always exits 0 — never blocks)
    map_md_path = str(root / "docs" / "cerebrofy" / "cerebrofy_map.md")
    db_path = str(root / ".cerebrofy" / "db" / "cerebrofy.db")
    post_merge_block = _generate_post_merge_script(map_md_path, db_path)

    post_merge = hooks_dir / "post-merge"
    if not post_merge.exists():
        post_merge.write_text(f"#!/bin/sh\n{post_merge_block}", encoding="utf-8")
        try:
            os.chmod(post_merge, 0o755)
        except (NotImplementedError, OSError):
            pass
    elif not has_cerebrofy_marker(post_merge):
        existing = post_merge.read_text(encoding="utf-8")
        post_merge.write_text(existing.rstrip("\n") + "\n" + post_merge_block, encoding="utf-8")
        warnings.append(f"Warning: Pre-existing hook at {post_merge} — appending Cerebrofy call.")

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
