"""Unit tests for cerebrofy.utils.paths — shared repo-root resolution (Wave A security hardening).

Covers the strict resolution order:
    bound root (MCP server) > CEREBROFY_ROOT env > CWD walk-up

Plus the server-side integer-arg caps (``_parse_int_arg``) that harden the
MCP tool handlers against unbounded ``top_k`` / ``limit`` / ``top`` values.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from cerebrofy.utils.paths import (
    CONFIG_MARKER,
    DB_MARKER,
    InvalidRepoRootError,
    find_repo_root,
    require_repo_root,
    reset_bound_root,
    reset_root_boundary,
    set_bound_root,
    set_root_boundary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_root_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with no bound root and no CEREBROFY_ROOT env var.

    The bound root is process-global (set by ``set_bound_root`` at MCP server
    start-up); tests must not pollute one another across that boundary.
    """
    reset_bound_root()
    monkeypatch.delenv("CEREBROFY_ROOT", raising=False)
    yield
    reset_bound_root()


def _make_repo(tmp_path: Path, *, db: bool = False) -> Path:
    """Create a minimal Cerebrofy repo tree under *tmp_path* and return its root."""
    root = tmp_path / "repo"
    cfg_dir = root / ".cerebrofy"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "lobes:\n  src: src/\nembedding_model: local\n",
        encoding="utf-8",
    )
    if db:
        db_dir = cfg_dir / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        (db_dir / "cerebrofy.db").write_text("v1", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# CEREBROFY_ROOT env override
# ---------------------------------------------------------------------------

def test_env_root_is_used_when_cwd_is_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CEREBROFY_ROOT wins even when CWD is a completely unrelated directory."""
    root = _make_repo(tmp_path)
    monkeypatch.setenv("CEREBROFY_ROOT", str(root))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = find_repo_root(Path.cwd())
    assert result == root


def test_env_root_resolves_to_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setenv("CEREBROFY_ROOT", str(root))

    result = find_repo_root(Path.cwd())
    assert result is not None
    assert result == root.resolve()


# ---------------------------------------------------------------------------
# Walk-up discovery
# ---------------------------------------------------------------------------

def test_walk_up_finds_config_from_nested_dir(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    nested = root / "src" / "pkg" / "deep"
    nested.mkdir(parents=True)

    result = find_repo_root(nested)
    assert result == root


def test_walk_up_starts_from_cwd_when_none_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(tmp_path)
    nested = root / "src" / "lib"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    result = find_repo_root()  # start defaults to Path.cwd()
    assert result == root


def test_walk_up_handles_file_path_as_start(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    some_file = root / "src" / "mod.py"
    some_file.parent.mkdir(parents=True)
    some_file.write_text("pass\n", encoding="utf-8")

    result = find_repo_root(some_file)
    assert result == root


def test_walk_up_returns_none_when_no_marker(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    nested = plain / "a" / "b"
    nested.mkdir(parents=True)

    assert find_repo_root(nested) is None


# ---------------------------------------------------------------------------
# Invalid CEREBROFY_ROOT env value (fail-closed)
# ---------------------------------------------------------------------------

def test_invalid_env_root_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit CEREBROFY_ROOT that lacks the config must raise, not silently
    fall through to CWD walk-up."""
    bogus = tmp_path / "not_a_repo"
    bogus.mkdir()
    monkeypatch.setenv("CEREBROFY_ROOT", str(bogus))

    with pytest.raises(InvalidRepoRootError):
        find_repo_root(tmp_path)


def test_invalid_env_root_error_message_is_generic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The error message should guide the operator, not leak the resolved path."""
    bogus = tmp_path / "not_a_repo"
    bogus.mkdir()
    monkeypatch.setenv("CEREBROFY_ROOT", str(bogus))

    with pytest.raises(InvalidRepoRootError) as exc_info:
        find_repo_root(tmp_path)
    msg = str(exc_info.value)
    assert ".cerebrofy/config.yaml" in msg
    # Should mention the env var name so operators know what to fix.
    assert "CEREBROFY_ROOT" in msg


def test_env_root_outside_boundary_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CEREBROFY_ROOT resolving outside the allowed boundary must raise."""
    root = _make_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("CEREBROFY_ROOT", str(root))

    with pytest.raises(InvalidRepoRootError):
        find_repo_root(tmp_path, boundary=other)


# ---------------------------------------------------------------------------
# DB_MARKER variant
# ---------------------------------------------------------------------------

def test_db_marker_walk_up_finds_db(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, db=True)
    nested = root / "src" / "nested"
    nested.mkdir(parents=True)

    result = find_repo_root(nested, marker=DB_MARKER)
    assert result == root


def test_db_marker_returns_none_without_db(tmp_path: Path) -> None:
    """Config-marker repo but no DB file — DB marker walk-up should return None."""
    root = _make_repo(tmp_path, db=False)
    nested = root / "src" / "nested"
    nested.mkdir(parents=True)

    result = find_repo_root(nested, marker=DB_MARKER)
    assert result is None


# ---------------------------------------------------------------------------
# Bound root (MCP server start-up binding)
# ---------------------------------------------------------------------------

def test_bound_root_is_returned_regardless_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(tmp_path)
    set_bound_root(root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    # Even with a valid CEREBROFY_ROOT set, the bound root wins.
    monkeypatch.setenv("CEREBROFY_ROOT", str(tmp_path))
    assert find_repo_root(Path.cwd()) == root


def test_bound_root_takes_priority_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(tmp_path)
    set_bound_root(root)
    monkeypatch.setenv("CEREBROFY_ROOT", str(tmp_path / "wrong"))

    assert find_repo_root() == root


def test_require_repo_root_returns_bound_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(tmp_path)
    set_bound_root(root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert require_repo_root(Path.cwd()) == root


# ---------------------------------------------------------------------------
# Launch boundary (C1/S1) — process-wide clip on CWD routing
# ---------------------------------------------------------------------------

def test_launch_boundary_allows_walk_up_inside_project(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    nested = root / "src" / "pkg" / "deep"
    nested.mkdir(parents=True)
    set_root_boundary(root)

    assert find_repo_root(nested) == root


def test_launch_boundary_blocks_sibling_project(tmp_path: Path) -> None:
    root_a = _make_repo(tmp_path / "a")
    root_b = _make_repo(tmp_path / "b")
    (root_b / "src").mkdir(parents=True)
    set_root_boundary(root_a)

    assert find_repo_root(root_a / "src") == root_a
    assert find_repo_root(root_b / "src") is None


def test_launch_boundary_at_workspace_root_allows_child_repos(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    child = _make_repo(workspace)          # workspace/repo
    sibling = _make_repo(tmp_path / "elsewhere")
    (child / "src").mkdir()
    (sibling / "src").mkdir()
    set_root_boundary(workspace)

    assert find_repo_root(workspace) is None        # workspace itself is not a project
    assert find_repo_root(child / "src") == child   # child repos are served
    assert find_repo_root(sibling / "src") is None  # siblings outside are not


def test_explicit_bound_root_wins_over_launch_boundary(tmp_path: Path) -> None:
    root_a = _make_repo(tmp_path / "a")
    root_b = _make_repo(tmp_path / "b")
    set_bound_root(root_a)
    set_root_boundary(root_b)

    assert find_repo_root(root_b / "src") == root_a


def test_env_root_outside_launch_boundary_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_a = _make_repo(tmp_path / "a")
    root_b = _make_repo(tmp_path / "b")
    set_root_boundary(root_a)
    monkeypatch.setenv("CEREBROFY_ROOT", str(root_b))

    with pytest.raises(InvalidRepoRootError):
        find_repo_root(tmp_path)


def test_reset_bound_root_clears_launch_boundary(tmp_path: Path) -> None:
    root_a = _make_repo(tmp_path / "a")
    root_b = _make_repo(tmp_path / "b")
    (root_b / "src").mkdir()
    set_root_boundary(root_a)
    reset_bound_root()

    assert find_repo_root(root_b / "src") == root_b


def test_reset_root_boundary_restores_walk_up(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    nested = root / "src"
    nested.mkdir()
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    set_root_boundary(blocked)

    assert find_repo_root(nested) is None
    reset_root_boundary()
    assert find_repo_root(nested) == root


# ---------------------------------------------------------------------------
# Reset / require_repo_root
# ---------------------------------------------------------------------------

def test_reset_bound_root_allows_walk_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bound = _make_repo(tmp_path)
    set_bound_root(bound)
    reset_bound_root()

    other = tmp_path / "other_repo"
    other.mkdir()
    (other / ".cerebrofy").mkdir()
    (other / ".cerebrofy" / "config.yaml").write_text("lobes: {}\n", encoding="utf-8")
    monkeypatch.chdir(other)

    assert find_repo_root() == other.resolve()


def test_require_repo_root_raises_when_no_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)

    with pytest.raises(FileNotFoundError, match="No Cerebrofy config"):
        require_repo_root(Path.cwd())


def test_require_repo_root_raises_when_env_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """require_repo_root must propagate InvalidRepoRootError from a bad env var
    rather than silently swallowing it."""
    bogus = tmp_path / "bogus"
    bogus.mkdir()
    monkeypatch.setenv("CEREBROFY_ROOT", str(bogus))

    with pytest.raises(InvalidRepoRootError):
        require_repo_root(Path.cwd())


# ---------------------------------------------------------------------------
# Markers exported for convenience
# ---------------------------------------------------------------------------

def test_config_marker_value() -> None:
    assert CONFIG_MARKER == ".cerebrofy/config.yaml"


def test_db_marker_value() -> None:
    assert DB_MARKER == ".cerebrofy/db/cerebrofy.db"


# ===========================================================================
# MCP server-side integer-arg caps  (Idea #25 / DoS hardening)
# ===========================================================================

pytest.importorskip("mcp")

from cerebrofy.mcp.server import (  # noqa: E402  (import after skip guard)
    _bootstrap_root,
    _bind_launch_boundary,
    _parse_int_arg,
    _run_cerebrofy,
    _MAX_LIMIT,
    _MAX_RESULT_TOP,
    _MAX_TOP_K,
)


# ---------------------------------------------------------------------------
# _parse_int_arg — clamping
# ---------------------------------------------------------------------------

def test_parse_int_arg_clamps_top_k_over_cap() -> None:
    value, err = _parse_int_arg({"top_k": 999}, "top_k", 10, maximum=_MAX_TOP_K)
    assert err is None
    assert value == _MAX_TOP_K


def test_parse_int_arg_clamps_limit_over_cap() -> None:
    value, err = _parse_int_arg({"limit": 99999}, "limit", 10, maximum=_MAX_LIMIT)
    assert err is None
    assert value == _MAX_LIMIT


def test_parse_int_arg_clamps_top_over_cap() -> None:
    value, err = _parse_int_arg({"top": 5000}, "top", 20, maximum=_MAX_RESULT_TOP)
    assert err is None
    assert value == _MAX_RESULT_TOP


def test_parse_int_arg_accepts_value_within_range() -> None:
    value, err = _parse_int_arg({"top_k": 25}, "top_k", 10, maximum=_MAX_TOP_K)
    assert err is None
    assert value == 25


def test_parse_int_arg_uses_default_when_missing() -> None:
    value, err = _parse_int_arg({}, "top_k", 10, maximum=_MAX_TOP_K)
    assert err is None
    assert value == 10


def test_parse_int_arg_clamps_below_minimum() -> None:
    value, err = _parse_int_arg({"top_k": 0}, "top_k", 10, maximum=_MAX_TOP_K)
    assert err is None
    assert value == 1  # minimum defaults to 1


# ---------------------------------------------------------------------------
# _parse_int_arg — type validation
# ---------------------------------------------------------------------------

def test_parse_int_arg_rejects_string() -> None:
    value, err = _parse_int_arg({"top_k": "abc"}, "top_k", 10, maximum=_MAX_TOP_K)
    assert err is not None
    assert value == 0
    assert "must be an integer" in err
    assert "top_k" in err


def test_parse_int_arg_rejects_none() -> None:
    value, err = _parse_int_arg({"top_k": None}, "top_k", 10, maximum=_MAX_TOP_K)
    assert err is not None
    assert value == 0
    assert "must be an integer" in err


def test_parse_int_arg_rejects_list() -> None:
    value, err = _parse_int_arg({"limit": [1, 2]}, "limit", 10, maximum=_MAX_LIMIT)
    assert err is not None
    assert value == 0
    assert "must be an integer" in err


def test_parse_int_arg_accepts_numeric_string() -> None:
    """A string like '42' should be coerced to int rather than rejected."""
    value, err = _parse_int_arg({"top_k": "42"}, "top_k", 10, maximum=_MAX_TOP_K)
    assert err is None
    assert value == 42


# ---------------------------------------------------------------------------
# _bootstrap_root — explicit binding only
# ---------------------------------------------------------------------------

def test_bootstrap_root_uses_explicit_root(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert _bootstrap_root(root) == root.resolve()


def test_bootstrap_root_returns_none_without_explicit_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default mode must keep per-call CWD routing (no process-wide binding)."""
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert _bootstrap_root(None) is None


def test_bootstrap_root_uses_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_repo(tmp_path)
    monkeypatch.setenv("CEREBROFY_ROOT", str(root))
    assert _bootstrap_root(None) == root.resolve()


def test_bootstrap_root_rejects_explicit_root_without_config(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus"
    bogus.mkdir()
    with pytest.raises(InvalidRepoRootError):
        _bootstrap_root(bogus)


# ---------------------------------------------------------------------------
# _bind_launch_boundary — no explicit pin → clipped CWD routing
# ---------------------------------------------------------------------------

def test_bind_launch_boundary_inside_project_sets_project_root(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    nested = root / "src"
    nested.mkdir()
    sibling = _make_repo(tmp_path / "sib")
    (sibling / "src").mkdir()

    assert _bind_launch_boundary(nested) == root
    # Boundary applies to every later lookup: the sibling project is unreachable.
    assert find_repo_root(nested) == root
    assert find_repo_root(sibling / "src") is None


def test_bind_launch_boundary_workspace_root_serves_children(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    child = _make_repo(workspace)      # workspace/repo
    (child / "src").mkdir()

    assert _bind_launch_boundary(workspace) is None
    assert find_repo_root(child / "src") == child


# ===========================================================================
# n10 — _run_cerebrofy default timeout uses the shared constant (not a literal)
# ===========================================================================


def test_default_mcp_command_timeout_constant() -> None:
    from cerebrofy.constants import DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS

    assert DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS == 300


def test_run_cerebrofy_default_timeout_matches_constant() -> None:
    import inspect

    from cerebrofy.constants import DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS

    sig = inspect.signature(_run_cerebrofy)
    assert sig.parameters["timeout"].default == DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS


def test_run_cerebrofy_forwards_timeout_to_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The configured timeout (not a literal) reaches the subprocess call."""
    import subprocess as _sp

    from cerebrofy.constants import DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        raise _sp.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(_sp.TimeoutExpired):
        _run_cerebrofy(["build"], str(tmp_path))

    assert captured["timeout"] == DEFAULT_MCP_COMMAND_TIMEOUT_SECONDS
