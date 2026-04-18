"""Git hook installer with idempotency sentinel support."""

from __future__ import annotations

import os
from pathlib import Path

# FR-020: sentinel format — supersedes earlier cerebrofy-hook-start/end format
HOOK_MARKER_START = "# BEGIN cerebrofy"
HOOK_MARKER_END = "# END cerebrofy"

# Canonical constant names per Phase 5 spec (T012 / FR-020).
HOOK_SENTINEL_BEGIN = HOOK_MARKER_START
HOOK_SENTINEL_END = HOOK_MARKER_END
HOOK_VERSION_MARKER = "# cerebrofy-hook-version:"

# Version 1 = warn-only (Phase 1). Version 2 = hard-block (Phase 3 upgrade).
# Shell block written into pre-push hook at install time.
# Use {hook_name} placeholder — filled by create_hook_file() / append_to_hook().
HOOK_SCRIPT_BLOCK = """\
{marker_start}
# cerebrofy-hook-version: 1
cerebrofy validate --hook {{hook_name}}
{marker_end}
""".format(marker_start=HOOK_MARKER_START, marker_end=HOOK_MARKER_END)

# Hard-block block used by upgrade_hook() when update latency target is met.
_HOOK_SCRIPT_V2: str = (
    f"{HOOK_SENTINEL_BEGIN}\n"
    f"{HOOK_VERSION_MARKER} 2\n"
    "if ! cerebrofy validate --hook pre-push; then\n"
    "    echo 'Cerebrofy: Structural drift detected. Run cerebrofy update to sync.'\n"
    "    exit 1\n"
    "fi\n"
    f"{HOOK_SENTINEL_END}\n"
)


def _get_hook_version(hook_content: str) -> int:
    """Find the cerebrofy sentinel block and return the version number.

    Returns 0 if no block or no version marker is found.
    """
    if HOOK_SENTINEL_BEGIN not in hook_content:
        return 0
    start_idx = hook_content.index(HOOK_SENTINEL_BEGIN)
    end_idx = hook_content.find(HOOK_SENTINEL_END, start_idx)
    if end_idx == -1:
        return 0
    block = hook_content[start_idx:end_idx]
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith(HOOK_VERSION_MARKER):
            try:
                return int(stripped[len(HOOK_VERSION_MARKER):].strip())
            except ValueError:
                return 0
    return 0


def _replace_hook_block(hook_content: str, new_block: str) -> str:
    """Replace the cerebrofy sentinel block with new_block.

    If no block exists, appends new_block at the end.
    """
    if HOOK_SENTINEL_BEGIN not in hook_content:
        return hook_content.rstrip("\n") + "\n" + new_block

    start_idx = hook_content.index(HOOK_SENTINEL_BEGIN)
    end_idx = hook_content.find(HOOK_SENTINEL_END, start_idx)
    if end_idx == -1:
        # Malformed — just replace from start marker to end
        return hook_content[:start_idx] + new_block

    end_idx += len(HOOK_SENTINEL_END)
    # Consume trailing newline after END sentinel if present
    if end_idx < len(hook_content) and hook_content[end_idx] == "\n":
        end_idx += 1

    return hook_content[:start_idx] + new_block + hook_content[end_idx:]


def upgrade_hook(hook_path: Path) -> None:
    """Upgrade the cerebrofy pre-push hook to version 2 (hard-block).

    Idempotent: no-op if already version 2. Replaces the entire sentinel block.
    """
    if not hook_path.exists():
        return
    content = hook_path.read_text(encoding="utf-8")
    if _get_hook_version(content) >= 2:
        return
    hook_path.write_text(_replace_hook_block(content, _HOOK_SCRIPT_V2), encoding="utf-8")


def has_cerebrofy_marker(hook_path: Path) -> bool:
    """Return True if the hook file already contains the cerebrofy sentinel."""
    if not hook_path.exists():
        return False
    return HOOK_MARKER_START in hook_path.read_text(encoding="utf-8")


def create_hook_file(hook_path: Path, hook_name: str, block: str | None = None) -> None:
    """Create a new executable hook file with the cerebrofy block."""
    b = block if block is not None else HOOK_SCRIPT_BLOCK.format(hook_name=hook_name)
    hook_path.write_text(f"#!/bin/sh\n{b}", encoding="utf-8")
    try:
        os.chmod(hook_path, 0o755)
    except (NotImplementedError, OSError):
        pass  # Windows — executability handled by git's hook runner


def append_to_hook(hook_path: Path, hook_name: str, block: str | None = None) -> str:
    """Append the cerebrofy block to an existing hook file. Returns a warning string."""
    b = block if block is not None else HOOK_SCRIPT_BLOCK.format(hook_name=hook_name)
    existing = hook_path.read_text(encoding="utf-8")
    hook_path.write_text(existing.rstrip("\n") + "\n" + b, encoding="utf-8")
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


def _is_cerebrofy_db_gitignored(root: Path) -> bool:
    """Return True if .cerebrofy/db/ is covered by a .gitignore entry.

    When True, the DB is not tracked by git, so a warn-only hook is appropriate.
    When False (not gitignored), the DB may be tracked, so a hard-block is used.
    """
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return False
    content = gitignore.read_text(encoding="utf-8")
    return any(
        pat in content
        for pat in (".cerebrofy/", ".cerebrofy/db", ".cerebrofy\\")
    )


def install_hooks(root: Path, config: object = None) -> list[str]:
    """Install cerebrofy pre-push and post-merge hooks. Returns any warning messages.

    Chooses the hook blocking mode based on .gitignore state:
    - If .cerebrofy/ is gitignored → warn-only (v1): DB drift won't corrupt git state.
    - If .cerebrofy/ is tracked by git → hard-block (v2): stale DB in commits breaks state.

    config is accepted for forward compatibility but paths are derived from root.
    """
    hooks_dir = root / ".git" / "hooks"
    warnings: list[str] = []

    # Choose pre-push blocking mode based on gitignore state.
    if _is_cerebrofy_db_gitignored(root):
        pre_push_block = HOOK_SCRIPT_BLOCK.format(hook_name="pre-push")
    else:
        pre_push_block = _HOOK_SCRIPT_V2

    # Pre-push hook: warn-only if DB is gitignored, hard-block if tracked
    pre_push = hooks_dir / "pre-push"
    if not pre_push.exists():
        create_hook_file(pre_push, "pre-push", block=pre_push_block)
    elif not has_cerebrofy_marker(pre_push):
        warnings.append(append_to_hook(pre_push, "pre-push", block=pre_push_block))

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


def add_gitignore_entry(repo_root: Path) -> None:
    """Append .cerebrofy/db/ and .mcp.json to .gitignore if not already present (FR-019)."""
    gitignore = repo_root / ".gitignore"
    entries = [".cerebrofy/db/", ".mcp.json"]
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
    else:
        content = ""
    to_add = [e for e in entries if e not in content]
    if not to_add:
        return
    gitignore.write_text(content.rstrip("\n") + "\n" + "\n".join(to_add) + "\n", encoding="utf-8")
