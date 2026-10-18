"""Git hook installer with idempotency sentinel support."""

from __future__ import annotations

import os
from pathlib import Path

from cerebrofy.arch.rules import rules_file_exists

# FR-020: sentinel format — supersedes earlier cerebrofy-hook-start/end format
HOOK_MARKER_START = "# BEGIN cerebrofy"
HOOK_MARKER_END = "# END cerebrofy"

# Canonical constant names per Phase 5 spec (T012 / FR-020).
HOOK_SENTINEL_BEGIN = HOOK_MARKER_START
HOOK_SENTINEL_END = HOOK_MARKER_END
HOOK_VERSION_MARKER = "# cerebrofy-hook-version:"

# Version 1 = warn-only (Phase 1). Version 2 = hard-block (Phase 3 upgrade).
# Version 3 adds the architecture drift check (v2/v1 body + arch segment).
# Version 4 upgrades the arch segment to always block violations (spec Alert
# Modes: pre-commit / pre-push "Blocks commit/push"); the validate section
# keeps following the gitignore consent model.
# Use {hook_name} placeholder — filled by create_hook_file() / append_to_hook().
_VALIDATE_WARN_BODY = """\
if ! cerebrofy validate --hook {hook_name} 2>/dev/null; then
    echo 'Cerebrofy: drift detected -- auto-syncing index...'
    if ! cerebrofy update; then
        echo 'Cerebrofy: index update failed. Push blocked.' >&2
        exit 1
    fi
    echo 'Cerebrofy: index synced.'
fi
"""

HOOK_SCRIPT_BLOCK = """\
{marker_start}
# cerebrofy-hook-version: 1
{warn_body}
{marker_end}
""".format(
    marker_start=HOOK_MARKER_START,
    marker_end=HOOK_MARKER_END,
    warn_body=_VALIDATE_WARN_BODY.rstrip("\n"),
)

# Pre-commit block: silently re-indexes changed files after every commit.
# Always exits 0 — index update is best-effort and must never block commits.
_HOOK_SCRIPT_PRE_COMMIT: str = (
    f"{HOOK_SENTINEL_BEGIN}\n"
    f"{HOOK_VERSION_MARKER} 1\n"
    "if [ -f \".cerebrofy/db/cerebrofy.db\" ]; then\n"
    "    cerebrofy update >/dev/null 2>&1 || true\n"
    "fi\n"
    f"{HOOK_SENTINEL_END}\n"
)

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


def _arch_segment(hook_name: str) -> str:
    """Return the shell segment invoking 'cerebrofy arch check'.

    Architecture violations always block the operation (spec Alert Modes:
    "Blocks commit/push"); only error-severity violations exit non-zero, so
    warning rules stay informational. The segment is inert unless
    .cerebrofy/arch-rules.yaml exists, which makes architecture alerts
    strictly opt-in (the rules file is created by 'cerebrofy arch init').
    """
    return (
        'if [ -f ".cerebrofy/arch-rules.yaml" ]; then\n'
        f"    if ! cerebrofy arch check --hook {hook_name}; then\n"
        f"        echo 'Cerebrofy: Architecture violations detected. "
        f"{'Push' if hook_name == 'pre-push' else 'Commit'} blocked.' >&2\n"
        "        exit 1\n"
        "    fi\n"
        "fi\n"
    )


def _v4_pre_push_block(hard: bool) -> str:
    """v4 pre-push block: validate section (warn or hard) + blocking arch section."""
    if hard:
        validate_part = _HOOK_SCRIPT_V2_BODY
    else:
        validate_part = _VALIDATE_WARN_BODY.format(hook_name="pre-push")
    return (
        f"{HOOK_SENTINEL_BEGIN}\n"
        f"{HOOK_VERSION_MARKER} 4\n"
        f"{validate_part}"
        f"{_arch_segment('pre-push')}"
        f"{HOOK_SENTINEL_END}\n"
    )


def _v4_pre_commit_block() -> str:
    """v4 pre-commit block: silent index sync + blocking arch section."""
    return (
        f"{HOOK_SENTINEL_BEGIN}\n"
        f"{HOOK_VERSION_MARKER} 4\n"
        "if [ -f \".cerebrofy/db/cerebrofy.db\" ]; then\n"
        "    cerebrofy update >/dev/null 2>&1 || true\n"
        "fi\n"
        f"{_arch_segment('pre-commit')}"
        f"{HOOK_SENTINEL_END}\n"
    )


# Hard-block validate body (v2 form), reused by the v4 pre-push builder.
_HOOK_SCRIPT_V2_BODY: str = (
    "if ! cerebrofy validate --hook pre-push; then\n"
    "    echo 'Cerebrofy: Structural drift detected. Run cerebrofy update to sync.'\n"
    "    exit 1\n"
    "fi\n"
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


def upgrade_hook(hook_path: Path, root: Path | None = None) -> str | None:
    """Upgrade a cerebrofy hook block to the newest version this repo supports.

    Versions: pre-push 1 (warn) / 2 (hard-block) / 3 (+ architecture alerts,
    warn-or-hard) / 4 (architecture violations always block); pre-commit 1
    (index sync) / 3 / 4. The arch-aware v4 is chosen whenever
    .cerebrofy/arch-rules.yaml exists under root.

    Idempotent: a no-op (returns None) when the file is missing, is not managed
    by cerebrofy, already carries the desired version, or is post-merge (v1
    stays). Returns a user-facing message after a successful upgrade.
    """
    if not hook_path.exists():
        return None
    content = hook_path.read_text(encoding="utf-8")
    current = _get_hook_version(content)
    if current == 0:
        return None  # no cerebrofy block — not ours to upgrade
    name = hook_path.name
    if name not in ("pre-commit", "pre-push"):
        return None
    if root is None:
        root = hook_path.parent.parent.parent  # <repo>/.git/hooks/<name>
    if rules_file_exists(root):
        desired, block = (
            (4, _v4_pre_push_block(_hook_hard_mode(root)))
            if name == "pre-push"
            else (4, _v4_pre_commit_block())
        )
    elif name == "pre-push":
        desired, block = 2, _HOOK_SCRIPT_V2
    else:
        desired, block = 1, _HOOK_SCRIPT_PRE_COMMIT
    if current >= desired:
        return None
    hook_path.write_text(_replace_hook_block(content, block), encoding="utf-8")
    return f"Cerebrofy: upgraded {name} hook to version {desired}."


def has_cerebrofy_marker(hook_path: Path) -> bool:
    """Return True if the hook file already contains the cerebrofy sentinel."""
    if not hook_path.exists():
        return False
    return HOOK_MARKER_START in hook_path.read_text(encoding="utf-8")


def create_hook_file(hook_path: Path, hook_name: str, block: str | None = None) -> None:
    """Create a new executable hook file with the cerebrofy block."""
    b = block if block is not None else HOOK_SCRIPT_BLOCK.format(hook_name=hook_name)
    with hook_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"#!/bin/sh\n{b}")
    try:
        os.chmod(hook_path, 0o755)
    except (NotImplementedError, OSError):
        pass  # Windows — executability handled by git's hook runner


def append_to_hook(hook_path: Path, hook_name: str, block: str | None = None) -> str:
    """Append the cerebrofy block to an existing hook file. Returns a warning string."""
    b = block if block is not None else HOOK_SCRIPT_BLOCK.format(hook_name=hook_name)
    existing = hook_path.open("r", encoding="utf-8", newline="\n").read()
    with hook_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(existing.rstrip("\n") + "\n" + b)
    return f"Warning: Pre-existing hook at {hook_path} — appending Cerebrofy call."


def _generate_post_merge_script(map_md_path: str, db_path: str) -> str:
    """Return the shell script body for the cerebrofy post-merge hook.

    map_md_path and db_path are injected as Python string literals at generation time
    (resolved from repo_root at install time — the shell script cannot read config.yaml).
    Script reads state_hash from cerebrofy_map.md; queries DB meta table via sqlite3.
    Always exits 0 (WARN-only, never blocks).

    Uses portable python detection (python3 → python fallback) so the script works
    on Linux, macOS, and Windows (Git for Windows / MSYS bash).
    """
    map_md_literal = repr(map_md_path)
    db_literal = repr(db_path)
    return f"""\
{HOOK_MARKER_START}
# cerebrofy-hook-version: 1
if command -v python3 >/dev/null 2>&1; then
    _CEREBROFY_PY=python3
elif command -v python >/dev/null 2>&1; then
    _CEREBROFY_PY=python
else
    exit 0
fi
$_CEREBROFY_PY << 'CEREBROFY_PM_CHECK'
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


def _hook_hard_mode(root: Path) -> bool:
    """Hard mode for the validate segment when .cerebrofy/ is tracked by git.

    The arch segment always blocks independently of this; only the
    validate-drift section follows the gitignore consent model.
    """
    return not _is_cerebrofy_db_gitignored(root)


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

    Chooses the validate blocking mode based on .gitignore state:
    - If .cerebrofy/ is gitignored → warn-only (v1): DB drift won't corrupt git state.
    - If .cerebrofy/ is tracked by git → hard-block (v2): stale DB in commits breaks state.

    When .cerebrofy/arch-rules.yaml exists (created by 'cerebrofy arch init'),
    v4 blocks are installed instead — same validate behavior plus the
    architecture drift check segment, which always blocks error-severity
    violations (warnings stay informational).

    config is accepted for forward compatibility but paths are derived from root.
    """
    hooks_dir = root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    # Choose blocking mode: gitignore consent model for validate, upgraded to
    # v4 when the arch rules file is present (architecture alerts are opt-in
    # via arch init; their violations always block).
    hard = _hook_hard_mode(root)
    if rules_file_exists(root):
        pre_push_block = _v4_pre_push_block(hard)
        pre_commit_block = _v4_pre_commit_block()
    else:
        pre_push_block = (
            _HOOK_SCRIPT_V2 if hard else HOOK_SCRIPT_BLOCK.format(hook_name="pre-push")
        )
        pre_commit_block = _HOOK_SCRIPT_PRE_COMMIT

    # Pre-commit hook: silently re-index on every commit (never blocks)
    pre_commit = hooks_dir / "pre-commit"
    if not pre_commit.exists():
        create_hook_file(pre_commit, "pre-commit", block=pre_commit_block)
    elif not has_cerebrofy_marker(pre_commit):
        warnings.append(append_to_hook(pre_commit, "pre-commit", block=pre_commit_block))

    # Pre-push hook: validate + auto-update if DB is gitignored, hard-block if tracked
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
        with post_merge.open("w", encoding="utf-8", newline="\n") as f:
            f.write(f"#!/bin/sh\n{post_merge_block}")
        try:
            os.chmod(post_merge, 0o755)
        except (NotImplementedError, OSError):
            pass
    elif not has_cerebrofy_marker(post_merge):
        existing = post_merge.open("r", encoding="utf-8", newline="\n").read()
        with post_merge.open("w", encoding="utf-8", newline="\n") as f:
            f.write(existing.rstrip("\n") + "\n" + post_merge_block)
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
