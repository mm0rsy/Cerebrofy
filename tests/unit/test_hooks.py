"""Unit tests for cerebrofy.hooks.installer — hook upgrade/downgrade (T056)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cerebrofy.hooks.installer import (
    HOOK_MARKER_END,
    HOOK_MARKER_START,
    HOOK_VERSION_MARKER,
    _generate_post_merge_script,
    _v3_pre_commit_block,
    _v3_pre_push_block,
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
# v3 — architecture drift hook segment
# ---------------------------------------------------------------------------


def _write_arch_rules(root: Path) -> None:
    """Create the arch rules file that activates the v3 hook segment."""
    cerebrofy = root / ".cerebrofy"
    cerebrofy.mkdir(parents=True, exist_ok=True)
    (cerebrofy / "arch-rules.yaml").write_text("rules: []\n", encoding="utf-8")


def _make_repo(tmp_path: Path, *, gitignored: bool, arch_rules: bool) -> Path:
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    gitignore = tmp_path / ".gitignore"
    if gitignored:
        gitignore.write_text(".cerebrofy/db/\n", encoding="utf-8")
    if arch_rules:
        _write_arch_rules(tmp_path)
    return tmp_path


def _hook_version(content: str) -> int:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(HOOK_VERSION_MARKER):
            return int(stripped[len(HOOK_VERSION_MARKER):].strip())
    return 0


def test_install_hooks_v3_when_arch_rules_present(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, gitignored=False, arch_rules=True)
    hooks = root / ".git" / "hooks"
    install_hooks(root)
    for name in ("pre-commit", "pre-push"):
        text = (hooks / name).read_text(encoding="utf-8")
        assert _hook_version(text) == 3
        assert "cerebrofy arch check --hook" in text
        assert "arch-rules.yaml" in text
        assert "Architecture violations detected." in text  # hard mode: tracked .cerebrofy


def test_install_hooks_v3_warn_mode_gitignored(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, gitignored=True, arch_rules=True)
    hooks = root / ".git" / "hooks"
    install_hooks(root)
    text = (hooks / "pre-push").read_text(encoding="utf-8")
    assert _hook_version(text) == 3
    assert "cerebrofy arch check --hook pre-push || true" in text
    assert "Architecture violations detected." not in text


def test_install_hooks_v1_v2_without_arch_rules(tmp_path: Path) -> None:
    """Without arch rules the historical v1/v2 blocks are unchanged."""
    root = _make_repo(tmp_path, gitignored=False, arch_rules=False)
    hooks = root / ".git" / "hooks"
    install_hooks(root)
    pre_commit = (hooks / "pre-commit").read_text(encoding="utf-8")
    pre_push = (hooks / "pre-push").read_text(encoding="utf-8")
    assert _hook_version(pre_commit) == 1
    assert _hook_version(pre_push) == 2
    assert "arch check" not in pre_push


def test_upgrade_hook_v1_to_v3_with_arch_rules(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, gitignored=False, arch_rules=True)
    hook = root / ".git" / "hooks" / "pre-push"
    _make_v1_hook(hook)
    message = upgrade_hook(hook, root=root)
    assert message == "Cerebrofy: upgraded pre-push hook to version 3."
    content = hook.read_text(encoding="utf-8")
    assert _hook_version(content) == 3
    assert "cerebrofy arch check --hook pre-push" in content


def test_upgrade_hook_idempotent_on_v3(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, gitignored=False, arch_rules=True)
    hook = root / ".git" / "hooks" / "pre-push"
    _make_v1_hook(hook)
    upgrade_hook(hook, root=root)
    content = hook.read_text(encoding="utf-8")
    assert upgrade_hook(hook, root=root) is None
    assert hook.read_text(encoding="utf-8") == content


def test_upgrade_hook_no_downgrade_when_rules_removed(tmp_path: Path) -> None:
    """A v3 block keeps grain when the rules file is later deleted (guard is inert)."""
    root = _make_repo(tmp_path, gitignored=False, arch_rules=True)
    hook = root / ".git" / "hooks" / "pre-push"
    _make_v1_hook(hook)
    upgrade_hook(hook, root=root)
    assert _hook_version(hook.read_text(encoding="utf-8")) == 3
    (root / ".cerebrofy" / "arch-rules.yaml").unlink()
    assert upgrade_hook(hook, root=root) is None
    assert _hook_version(hook.read_text(encoding="utf-8")) == 3


def test_upgrade_hook_leaves_post_merge_alone(tmp_path: Path) -> None:
    hook = tmp_path / "post-merge"
    hook.write_text(
        f"#!/bin/sh\n{HOOK_MARKER_START}\n{HOOK_VERSION_MARKER} 1\nexit 0\n{HOOK_MARKER_END}\n",
        encoding="utf-8",
    )
    assert upgrade_hook(hook) is None
    assert _hook_version(hook.read_text(encoding="utf-8")) == 1


def test_upgrade_hook_skips_foreign_hooks(tmp_path: Path) -> None:
    hook = tmp_path / "pre-push"
    hook.write_text("#!/bin/sh\necho not ours\n", encoding="utf-8")
    assert upgrade_hook(hook) is None
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\necho not ours\n"


def test_v3_blocks_contain_rules_file_guard() -> None:
    for block in (_v3_pre_push_block(True), _v3_pre_commit_block(False)):
        assert '[ -f ".cerebrofy/arch-rules.yaml" ]' in block
        assert "# END cerebrofy" in block


def test_v3_hard_block_arch_check_execution(tmp_path: Path) -> None:
    """The generated shell segment actually blocks when arch check exits non-zero."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "cerebrofy"
    stub.write_text("#!/bin/sh\nif [ \"$1\" = arch ]; then exit 1; fi\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)

    hook = tmp_path / "pre-push"
    hook.write_text(f"#!/bin/sh\n{_v3_pre_push_block(True)}", encoding="utf-8")
    hook.chmod(0o755)

    (tmp_path / ".cerebrofy").mkdir()  # guard must see the rules file
    (tmp_path / ".cerebrofy" / "arch-rules.yaml").touch()

    env_path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    result = subprocess.run(
        [str(hook)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": env_path},
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "Architecture violations detected. Push blocked." in result.stderr


def test_v3_warn_block_arch_failure_does_not_block(tmp_path: Path) -> None:
    """Warn-only: a failing arch check does NOT block the hook."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "cerebrofy"
    stub.write_text("#!/bin/sh\nif [ \"$1\" = arch ]; then exit 1; fi\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)

    hook = tmp_path / "pre-push"
    hook.write_text(f"#!/bin/sh\n{_v3_pre_push_block(False)}", encoding="utf-8")
    hook.chmod(0o755)

    env_path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    (tmp_path / ".cerebrofy").mkdir()
    (tmp_path / ".cerebrofy" / "arch-rules.yaml").touch()  # guard must pass
    result = subprocess.run(
        [str(hook)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": env_path},
        cwd=tmp_path,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# cerebrofy update wiring (_upgrade_git_hooks)
# ---------------------------------------------------------------------------


def test_update_upgrades_stale_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cerebrofy.commands.update import _upgrade_git_hooks

    root = _make_repo(tmp_path, gitignored=False, arch_rules=True)
    hook = root / ".git" / "hooks" / "pre-push"
    _make_v1_hook(hook)

    _upgrade_git_hooks(root)
    assert _hook_version(hook.read_text(encoding="utf-8")) == 3
    assert "version 3" in capsys.readouterr().out


def test_update_hook_upgrade_is_silent_when_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from cerebrofy.commands.update import _upgrade_git_hooks

    root = _make_repo(tmp_path, gitignored=False, arch_rules=False)
    hook = root / ".git" / "hooks" / "pre-push"
    (root / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    hook.write_text(
        f"#!/bin/sh\n{HOOK_MARKER_START}\n{HOOK_VERSION_MARKER} 2\nexit 0\n"
        f"{HOOK_MARKER_END}\n",
        encoding="utf-8",
    )

    _upgrade_git_hooks(root)  # already v2, no rules file → v2 is desired
    assert capsys.readouterr().out == ""


def test_update_hook_upgrade_survives_errors(tmp_path: Path) -> None:
    """A corrupt hook file must never fail the update command."""
    from cerebrofy.commands.update import _upgrade_git_hooks

    root = _make_repo(tmp_path, gitignored=False, arch_rules=True)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_bytes(b"\xff\xfe not utf-8")  # read_text will raise UnicodeDecodeError

    _upgrade_git_hooks(root)  # must not raise
    assert hook.read_bytes().startswith(b"\xff\xfe")  # corrupted block left untouched


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
    """install_hooks creates pre-commit, pre-push and post-merge hooks in a fresh repo."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    install_hooks(tmp_path)
    assert (hooks_dir / "pre-commit").exists()
    assert (hooks_dir / "pre-push").exists()
    assert (hooks_dir / "post-merge").exists()


def test_install_hooks_pre_commit_never_blocks(tmp_path: Path) -> None:
    """pre-commit hook must always exit 0 — it is best-effort and must not block commits."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    install_hooks(tmp_path)
    content = (hooks_dir / "pre-commit").read_text(encoding="utf-8")
    assert "cerebrofy update" in content
    assert "|| true" in content or "exit 0" in content


def test_install_hooks_idempotent(tmp_path: Path) -> None:
    """Calling install_hooks twice does not duplicate the marker."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    install_hooks(tmp_path)
    install_hooks(tmp_path)
    pre_push = (hooks_dir / "pre-push").read_text(encoding="utf-8")
    assert pre_push.count(HOOK_MARKER_START) == 1
    pre_commit = (hooks_dir / "pre-commit").read_text(encoding="utf-8")
    assert pre_commit.count(HOOK_MARKER_START) == 1


def test_install_hooks_post_merge_uses_state_hash_check(tmp_path: Path) -> None:
    """post-merge hook must contain state_hash logic, not just cerebrofy validate."""
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    install_hooks(tmp_path)
    content = (hooks_dir / "post-merge").read_text(encoding="utf-8")
    assert "state_hash" in content or "State Hash" in content
