"""Unit tests for cerebrofy.hooks.installer — hook upgrade/downgrade (T056)."""

from __future__ import annotations

import os
from pathlib import Path

from cerebrofy.hooks.installer import (
    HOOK_MARKER_END,
    HOOK_MARKER_START,
    HOOK_VERSION_MARKER,
    _generate_post_merge_script,
    install_hooks,
    upgrade_hook,
)


# ---------------------------------------------------------------------------
# upgrade_hook
# ---------------------------------------------------------------------------


def _make_v1_hook(path: Path, hook_name: str = "pre-push") -> None:
    """Write a minimal v1 warn-only hook at path."""
    path.write_text(
        f"#!/bin/sh\n"
        f"{HOOK_MARKER_START}\n"
        f"{HOOK_VERSION_MARKER} 1\n"
        f"cerebrofy validate --hook {hook_name}\n"
        f"{HOOK_MARKER_END}\n",
        encoding="utf-8",
    )


def test_upgrade_hook_bumps_to_version_2(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)
    upgrade_hook(hook)
    content = hook.read_text(encoding="utf-8")
    assert f"{HOOK_VERSION_MARKER} 2" in content
    assert f"{HOOK_VERSION_MARKER} 1" not in content


def test_upgrade_hook_adds_hard_block_logic(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)
    upgrade_hook(hook)
    content = hook.read_text(encoding="utf-8")
    # Hard-block form uses if ! cerebrofy validate syntax
    assert "if !" in content or "exit 1" in content


def test_upgrade_hook_preserves_sentinels(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)
    upgrade_hook(hook)
    content = hook.read_text(encoding="utf-8")
    assert HOOK_MARKER_START in content
    assert HOOK_MARKER_END in content


def test_upgrade_hook_idempotent(tmp_path: Path) -> None:
    """Calling upgrade_hook twice is a no-op on the second call."""
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)
    upgrade_hook(hook)
    content_after_first = hook.read_text(encoding="utf-8")
    upgrade_hook(hook)
    assert hook.read_text(encoding="utf-8") == content_after_first


def test_upgrade_hook_noop_when_file_missing(tmp_path: Path) -> None:
    """upgrade_hook on a non-existent path does nothing (no exception)."""
    upgrade_hook(tmp_path / "nonexistent")

# ---------------------------------------------------------------------------
# _generate_post_merge_script
# ---------------------------------------------------------------------------


def test_generate_post_merge_script_contains_paths(tmp_path: Path) -> None:
    map_md = str(tmp_path / "docs" / "cerebrofy" / "cerebrofy_map.md")
    db = str(tmp_path / ".cerebrofy" / "db" / "cerebrofy.db")
    script = _generate_post_merge_script(map_md, db)
    assert repr(map_md) in script
    assert repr(db) in script


def test_generate_post_merge_script_has_sentinels(tmp_path: Path) -> None:
    script = _generate_post_merge_script("/map.md", "/db")
    assert HOOK_MARKER_START in script
    assert HOOK_MARKER_END in script


def test_generate_post_merge_script_exits_0(tmp_path: Path) -> None:
    """Generated script exits 0 even when map.md and db don't exist."""
    import subprocess

    script = _generate_post_merge_script("/nonexistent/map.md", "/nonexistent/db")
    hook = tmp_path / "post-merge"
    hook.write_text(f"#!/bin/sh\n{script}", encoding="utf-8")
    os.chmod(hook, 0o755)

    result = subprocess.run([str(hook)], capture_output=True, text=True)
    assert result.returncode == 0, f"Script must exit 0. stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# install_hooks idempotency
# ---------------------------------------------------------------------------


def test_install_hooks_creates_hooks(tmp_path: Path) -> None:
    """install_hooks creates both pre-push and post-merge hooks in a fresh repo."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    install_hooks(tmp_path)
    assert (hooks_dir / "pre-push").exists()
    assert (hooks_dir / "post-merge").exists()


def test_install_hooks_idempotent(tmp_path: Path) -> None:
    """Calling install_hooks twice does not duplicate the marker."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    install_hooks(tmp_path)
    install_hooks(tmp_path)
    pre_push = (hooks_dir / "pre-push").read_text(encoding="utf-8")
    assert pre_push.count(HOOK_MARKER_START) == 1


def test_install_hooks_post_merge_uses_state_hash_check(tmp_path: Path) -> None:
    """post-merge hook must contain state_hash logic, not just cerebrofy validate."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    install_hooks(tmp_path)
    content = (hooks_dir / "post-merge").read_text(encoding="utf-8")
    assert "state_hash" in content or "State Hash" in content
