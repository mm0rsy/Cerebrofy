"""Shared repository-root resolution for Cerebrofy (Idea #01, security hardening).

Single source of truth for discovering the Cerebrofy project root. Previously
every command and tool duplicated a "walk up from CWD looking for
.cerebrofy/config.yaml" helper, which let a manipulated working directory
silently redirect the server at a *different* project's databases
(``cerebrofy.db`` / ``sessions.db`` / ``memories.db``).

There is now one helper with a strict resolution order:

    process binding (:func:`set_bound_root`, set by the MCP server for
        ``--root`` / ``CEREBROFY_ROOT``; fail-closed if invalid)
        > ``CEREBROFY_ROOT`` env var (fail-closed if invalid)
        > walk up from *start* (defaults to CWD) for ``.cerebrofy/config.yaml``

Without an explicit binding the walk-up runs per call, preserving the documented
CWD routing (one MCP entry serving multiple repos). Two hardening layers apply:

* the MCP server sets a **launch boundary** (:func:`set_root_boundary`) at
  start-up — routing may still follow the CWD per call, but never leaves the
  directory the server was launched from: inside a project the boundary is that
  project root, and at a non-project directory (e.g. a workspace root) it is
  the launch CWD itself, so the repos beneath it are still served while
  siblings and parents are not;
* an explicit binding (``--root`` / ``CEREBROFY_ROOT``) wins over the boundary
  and skips the walk-up entirely, so a compromised CWD cannot redirect the
  server to another project.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Canonical marker file that identifies a Cerebrofy project root.
CONFIG_MARKER = ".cerebrofy/config.yaml"

#: Marker used by the analysis CLI commands (silo / coverage-gap) which only
#: need an *indexed* project (the index DB, not just a config file).
DB_MARKER = ".cerebrofy/db/cerebrofy.db"


class InvalidRepoRootError(ValueError):
    """Raised when an explicitly-provided repo root is unusable.

    An operator pointing the MCP server's ``--root`` or ``CEREBROFY_ROOT`` at the
    wrong place should fail loudly and immediately rather than silently scanning a sibling
    project. This is intentionally distinct from "root not found" (which is
    recoverable via walk-up) because an *explicit* binding is unambiguous
    operator intent.
    """


# Process-wide root bound by the MCP server at start-up. When set, every
# :func:`find_repo_root` call returns this value regardless of CWD, eliminating
# the cross-project CWD-binding hazard. CLI invocations never set it (they
# resolve per-call via env/walk-up) and tests reset it via
# :func:`reset_bound_root`.
_bound_root: Path | None = None

#: Process-wide launch boundary (set by the MCP server at start-up when no
#: explicit root is given). The CWD walk-up never escapes this directory: a
#: server launched inside project A cannot route at sibling project B, while a
#: server launched at a workspace root can still serve every repo beneath it.
_root_boundary: Path | None = None


def set_root_boundary(boundary: Path | str | None) -> None:
    """Bind the process-wide launch boundary (MCP server start-up)."""
    global _root_boundary
    _root_boundary = Path(boundary).resolve() if boundary else None


def reset_root_boundary() -> None:
    """Clear the launch boundary (test hygiene)."""
    global _root_boundary
    _root_boundary = None


def set_bound_root(root: Path | str | None) -> None:
    """Bind the repo root for the running process (MCP server start-up)."""
    global _bound_root
    _bound_root = Path(root).resolve() if root else None


def reset_bound_root() -> None:
    """Clear any bound root and launch boundary (test hygiene)."""
    global _bound_root, _root_boundary
    _bound_root = None
    _root_boundary = None


def find_repo_root(
    start: Path | None = None,
    *,
    boundary: Path | None = None,
    marker: str = CONFIG_MARKER,
) -> Path | None:
    """Return the Cerebrofy repo root, or ``None`` if none is found.

    Resolution order:

      1. A bound root (set via :func:`set_bound_root` by the MCP server).
      2. The ``CEREBROFY_ROOT`` env var — must point at a directory containing
         ``.cerebrofy/config.yaml`` else :class:`InvalidRepoRootError` is
         raised. Fail-closed: an explicit binding that is wrong should be
         noticed immediately, not silently overridden by a CWD walk-up.
      3. Walk up from *start* (defaults to CWD) for *marker*
         (defaults to ``.cerebrofy/config.yaml``).

    *boundary* optionally clips the walk so it never escapes a parent project
    (returns ``None`` instead of scanning above the boundary). When *boundary*
    is ``None`` and the MCP server set a launch boundary
    (:func:`set_root_boundary`), that process boundary applies. *marker* lets
    callers that only need an indexed tree (the silo / coverage-gap commands)
    search for the DB file instead of the config.
    """
    if boundary is None:
        boundary = _root_boundary

    if _bound_root is not None:
        return _bound_root

    env_root = os.environ.get("CEREBROFY_ROOT")
    if env_root:
        root = Path(env_root).resolve()
        if not (root / CONFIG_MARKER).is_file():
            raise InvalidRepoRootError(
                f"CEREBROFY_ROOT is set to {env_root!r} but "
                f".cerebrofy/config.yaml was not found there. Unset the "
                f"env var or point it at a valid Cerebrofy project."
            )
        if boundary is not None and not root.is_relative_to(boundary):
            raise InvalidRepoRootError(
                f"CEREBROFY_ROOT ({env_root!r}) resolves outside the allowed boundary."
            )
        return root

    start = start if start is not None else Path.cwd()
    current = (start if start.is_dir() else start.parent).resolve()
    for candidate in (current, *current.parents):
        if boundary is not None and not candidate.is_relative_to(boundary):
            break
        if (candidate / marker).exists():
            return candidate
    return None


def require_repo_root(
    start: Path | None = None, *, boundary: Path | None = None
) -> Path:
    """Like :func:`find_repo_root` but raises ``FileNotFoundError`` when missing.

    Used by code that needs a root to proceed and wants a clear, path-free
    error message rather than propagating ``None``.
    """
    root = find_repo_root(start, boundary=boundary)
    if root is None:
        raise FileNotFoundError(
            "No Cerebrofy config found in the current directory or any parent. "
            "Run 'cerebrofy init' first."
        )
    return root
