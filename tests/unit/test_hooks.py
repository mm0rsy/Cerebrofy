"""Unit tests for cerebrofy.hooks.installer — hook upgrade/downgrade (T056)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cerebrofy.hooks.installer import (
    HOOK_MARKER_END,
    HOOK_MARKER_START,
    _generate_post_merge_script,
    downgrade_to_warn_only,
    install_hooks,
    upgrade_to_hard_block,
)


# ---------------------------------------------------------------------------
# upgrade_to_hard_block
# ---------------------------------------------------------------------------


def _make_v1_hook(path: Path, hook_name: str = "pre-push") -> None:
    """Write a minimal v1 warn-only hook at path."""
    path.write_text(
        f"#!/bin/sh\n"
        f"{HOOK_MARKER_START}\n"
        f"# cerebrofy-hook-version: 1\n"
        f"cerebrofy validate --hook {hook_name}\n"
        f"{HOOK_MARKER_END}\n",
        encoding="utf-8",
    )


def test_upgrade_replaces_version_marker(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)
    upgrade_to_hard_block(hook)
    content = hook.read_text(encoding="utf-8")
    assert "# cerebrofy-hook-version: 2" in content
    assert "# cerebrofy-hook-version: 1" not in content


def test_upgrade_adds_exit_code_propagation(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)
    upgrade_to_hard_block(hook)
    content = hook.read_text(encoding="utf-8")
    # Hard-block requires exit code check after validate call
    assert "exit_code=$?" in content or "exit 1" in content


def test_upgrade_preserves_sentinels(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)
    upgrade_to_hard_block(hook)
    content = hook.read_text(encoding="utf-8")
    assert HOOK_MARKER_START in content
    assert HOOK_MARKER_END in content


def test_upgrade_emits_warning_when_sentinels_absent(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Hook without cerebrofy sentinels → warning emitted, file unchanged."""
    hook = tmp_path / "pre-push"
    original = "#!/bin/sh\ncerebrofy validate\n"
    hook.write_text(original, encoding="utf-8")
    upgrade_to_hard_block(hook)
    # File must be unchanged
    assert hook.read_text(encoding="utf-8") == original
    # Warning must have been emitted
    captured = capsys.readouterr()
    assert "manual upgrade" in captured.err.lower() or "warning" in captured.err.lower()


def test_upgrade_noop_when_file_missing(tmp_path: Path) -> None:
    """upgrade_to_hard_block on a non-existent path does nothing (no exception)."""
    upgrade_to_hard_block(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# downgrade_to_warn_only
# ---------------------------------------------------------------------------


def _make_v2_hook(path: Path, hook_name: str = "pre-push") -> None:
    """Write a minimal v2 hard-block hook at path."""
    path.write_text(
        f"#!/bin/sh\n"
        f"{HOOK_MARKER_START}\n"
        f"# cerebrofy-hook-version: 2\n"
        f"cerebrofy validate --hook {hook_name}\n"
        f"exit_code=$?\n"
        f"if [ $exit_code -ne 0 ]; then exit 1; fi\n"
        f"{HOOK_MARKER_END}\n",
        encoding="utf-8",
    )


def test_downgrade_replaces_version_marker(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v2_hook(hook)
    downgrade_to_warn_only(hook)
    content = hook.read_text(encoding="utf-8")
    assert "# cerebrofy-hook-version: 1" in content
    assert "# cerebrofy-hook-version: 2" not in content


def test_downgrade_removes_exit_code_propagation(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v2_hook(hook)
    downgrade_to_warn_only(hook)
    content = hook.read_text(encoding="utf-8")
    # Hard-block lines must be gone
    assert "exit_code=$?" not in content
    assert "if [ $exit_code -ne 0 ]" not in content


def test_downgrade_preserves_sentinels(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    _make_v2_hook(hook)
    downgrade_to_warn_only(hook)
    content = hook.read_text(encoding="utf-8")
    assert HOOK_MARKER_START in content
    assert HOOK_MARKER_END in content


def test_downgrade_noop_when_sentinels_absent(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    original = "#!/bin/sh\ncerebrofy validate\n"
    hook.write_text(original, encoding="utf-8")
    downgrade_to_warn_only(hook)
    assert hook.read_text(encoding="utf-8") == original


def test_downgrade_noop_when_file_missing(tmp_path: Path) -> None:
    downgrade_to_warn_only(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# Round-trip: upgrade → downgrade
# ---------------------------------------------------------------------------


def test_upgrade_downgrade_roundtrip(tmp_path: Path) -> None:
    """Upgrade then downgrade must restore warn-only validate call."""
    hook = tmp_path / "pre-push"
    _make_v1_hook(hook)

    upgrade_to_hard_block(hook)
    downgrade_to_warn_only(hook)

    restored = hook.read_text(encoding="utf-8")
    assert "# cerebrofy-hook-version: 1" in restored
    assert "exit_code=$?" not in restored
    assert "cerebrofy validate" in restored


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
