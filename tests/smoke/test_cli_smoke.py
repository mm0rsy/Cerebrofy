"""
Subprocess-based smoke tests for the cerebrofy CLI.

These tests invoke `cerebrofy` as a real binary via subprocess — NOT via Click's
CliRunner — so they catch issues that in-process tests miss:
  - Missing directories (.git/hooks/) that would raise FileNotFoundError
  - PATH / entry-point registration problems
  - Permission errors on real filesystem operations
  - Any divergence between the installed binary and what Python imports

Marked with @pytest.mark.smoke so they can be run in isolation:
    uv run pytest tests/smoke/ -m smoke -v

The "build" scenario is guarded by @pytest.mark.slow and skipped unless
CEREBROFY_SMOKE_FULL=1 is set (or -m slow is passed), because it downloads
the ~130 MB ONNX model on first run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.smoke


def _cerebrofy(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run `cerebrofy <args>` as a real subprocess. Returns the CompletedProcess."""
    cmd = [sys.executable, "-m", "cerebrofy", *args]
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=merged_env,
    )


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one Python file. Returns the repo root."""
    _git(["init"], tmp_path)
    _git(["config", "user.email", "smoke@cerebrofy.test"], tmp_path)
    _git(["config", "user.name", "CerebrofySmoke"], tmp_path)

    src = tmp_path / "src" / "myapp"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "main.py").write_text(
        "def greet(name: str) -> str:\n    return f'hello {name}'\n",
        encoding="utf-8",
    )
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "initial"], tmp_path)
    return tmp_path


def _make_git_repo_no_hooks_dir(tmp_path: Path) -> Path:
    """Repo where .git/hooks/ is intentionally absent — reproduces the reported bug."""
    root = _make_git_repo(tmp_path)
    hooks_dir = root / ".git" / "hooks"
    if hooks_dir.exists():
        shutil.rmtree(hooks_dir)
    assert not hooks_dir.exists(), "setup: hooks dir should be gone"
    return root


# ---------------------------------------------------------------------------
# T-S01  cerebrofy init — golden path
# ---------------------------------------------------------------------------


def test_init_creates_scaffold(tmp_path: Path) -> None:
    """cerebrofy init --no-mcp creates all expected scaffold files and directories."""
    root = _make_git_repo(tmp_path)
    result = _cerebrofy("init", "--no-mcp", cwd=root)

    assert result.returncode == 0, (
        f"cerebrofy init failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    assert (root / ".cerebrofy" / "config.yaml").exists(), "config.yaml missing"
    assert (root / ".cerebrofy-ignore").exists(), ".cerebrofy-ignore missing"
    assert (root / ".cerebrofy" / "db").is_dir(), ".cerebrofy/db/ dir missing"
    assert (root / ".cerebrofy" / "queries").is_dir(), ".cerebrofy/queries/ dir missing"


def test_init_installs_hooks(tmp_path: Path) -> None:
    """cerebrofy init writes pre-commit, pre-push, and post-merge hooks."""
    root = _make_git_repo(tmp_path)
    result = _cerebrofy("init", "--no-mcp", cwd=root)

    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"

    hooks_dir = root / ".git" / "hooks"
    for hook_name in ("pre-commit", "pre-push", "post-merge"):
        hook_path = hooks_dir / hook_name
        assert hook_path.exists(), f"{hook_name} hook not created"
        assert "cerebrofy" in hook_path.read_text(encoding="utf-8"), (
            f"{hook_name} hook does not contain cerebrofy block"
        )
        assert oct(hook_path.stat().st_mode)[-3:] in ("755", "775", "777"), (
            f"{hook_name} hook is not executable"
        )


def test_init_hooks_when_hooks_dir_missing(tmp_path: Path) -> None:
    """cerebrofy init must not crash when .git/hooks/ does not exist.

    This is the exact regression that was reported: a bare git init (or worktrees,
    some CI environments) may not have .git/hooks/ pre-created.
    """
    root = _make_git_repo_no_hooks_dir(tmp_path)

    result = _cerebrofy("init", "--no-mcp", cwd=root)

    assert result.returncode == 0, (
        f"cerebrofy init crashed when .git/hooks/ was absent "
        f"(exit {result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    hooks_dir = root / ".git" / "hooks"
    assert hooks_dir.exists(), "init should have created .git/hooks/"
    assert (hooks_dir / "pre-commit").exists(), "pre-commit hook not created"
    assert (hooks_dir / "pre-push").exists(), "pre-push hook not created"


def test_init_updates_gitignore(tmp_path: Path) -> None:
    """cerebrofy init appends .cerebrofy/db/ to .gitignore."""
    root = _make_git_repo(tmp_path)
    _cerebrofy("init", "--no-mcp", cwd=root)

    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".cerebrofy/db/" in gitignore, ".cerebrofy/db/ not added to .gitignore"


def test_init_idempotent_on_existing_repo(tmp_path: Path) -> None:
    """cerebrofy init on an already-initialized repo warns but does not crash."""
    root = _make_git_repo(tmp_path)
    _cerebrofy("init", "--no-mcp", cwd=root)

    result = _cerebrofy("init", "--no-mcp", cwd=root)

    # Should warn (non-zero stderr) but exit 0 — not a hard failure
    assert result.returncode == 0, (
        f"Second cerebrofy init crashed (exit {result.returncode}):\n{result.stderr}"
    )
    assert "already exists" in result.stderr, (
        "Expected 'already exists' warning on second init, got:\n" + result.stderr
    )


def test_init_not_a_git_repo(tmp_path: Path) -> None:
    """cerebrofy init outside a git repo exits 1 with a clear error."""
    result = _cerebrofy("init", "--no-mcp", cwd=tmp_path)

    assert result.returncode == 1, (
        f"Expected exit 1 outside git repo, got {result.returncode}:\n{result.stdout}"
    )
    assert "git" in result.stderr.lower(), (
        "Expected error message mentioning 'git', got:\n" + result.stderr
    )


# ---------------------------------------------------------------------------
# T-S02  cerebrofy validate — no index → graceful error
# ---------------------------------------------------------------------------


def test_validate_without_index_exits_gracefully(tmp_path: Path) -> None:
    """cerebrofy validate before cerebrofy build exits cleanly with a helpful message."""
    root = _make_git_repo(tmp_path)
    _cerebrofy("init", "--no-mcp", cwd=root)

    result = _cerebrofy("validate", cwd=root)

    # cerebrofy validate exits 0 when there is no index (it is an informational
    # command, not an error state). What we verify is: no Python traceback, and
    # a message that tells the user what to do next.
    assert "Traceback" not in result.stdout, "Unexpected traceback in stdout"
    assert "Traceback" not in result.stderr, "Unexpected traceback in stderr"
    combined = result.stdout + result.stderr
    assert "cerebrofy build" in combined or "No index" in combined, (
        "Expected hint about cerebrofy build when no index exists, got:\n" + combined
    )


# ---------------------------------------------------------------------------
# T-S03  cerebrofy build — full index (slow, requires model download)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_build_creates_database_and_markdown(tmp_path: Path) -> None:
    """cerebrofy build indexes the repo and produces cerebrofy.db + markdown files.

    Skipped unless CEREBROFY_SMOKE_FULL=1 is set (model download ~130 MB).
    In CI this is cached at ~/.cache/fastembed between runs.
    """
    if not os.getenv("CEREBROFY_SMOKE_FULL"):
        pytest.skip("Set CEREBROFY_SMOKE_FULL=1 to run the full build smoke test")

    root = _make_git_repo(tmp_path)
    _cerebrofy("init", "--no-mcp", cwd=root)

    result = _cerebrofy("build", cwd=root)

    assert result.returncode == 0, (
        f"cerebrofy build failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    db = root / ".cerebrofy" / "db" / "cerebrofy.db"
    assert db.exists(), "cerebrofy.db not created after build"
    assert db.stat().st_size > 0, "cerebrofy.db is empty"

    map_md = root / "docs" / "cerebrofy" / "cerebrofy_map.md"
    assert map_md.exists(), "cerebrofy_map.md not generated"


@pytest.mark.slow
def test_update_after_build(tmp_path: Path) -> None:
    """cerebrofy update re-indexes a changed file without a full rebuild."""
    if not os.getenv("CEREBROFY_SMOKE_FULL"):
        pytest.skip("Set CEREBROFY_SMOKE_FULL=1 to run the full update smoke test")

    root = _make_git_repo(tmp_path)
    _cerebrofy("init", "--no-mcp", cwd=root)
    _cerebrofy("build", cwd=root)

    changed = root / "src" / "myapp" / "main.py"
    changed.write_text(
        "def greet(name: str) -> str:\n    return f'hello {name}'\n\n"
        "def farewell(name: str) -> str:\n    return f'goodbye {name}'\n",
        encoding="utf-8",
    )
    _git(["add", "."], root)
    _git(["commit", "-m", "add farewell"], root)

    result = _cerebrofy("update", "--all", cwd=root)

    assert result.returncode == 0, (
        f"cerebrofy update failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
