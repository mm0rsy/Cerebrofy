"""sqlite-vec loading with a supported-version guard (Wave A S2 / n11).

``sqlite-vec`` ships a native extension: loading it executes trusted native
code in-process, and its C-level API is not covered by a semver compatibility
promise. Cerebrofy therefore:

* pins the dependency to ``>=0.1.6,<0.2.0`` in ``pyproject.toml``, and
* re-checks the *installed* version at load time (this module), so a mismatched
  wheel fails loudly with an actionable message in every code path that loads
  the extension.

The import of ``sqlite_vec`` itself stays inside :func:`load_sqlite_vec`:
importing this module must not pay the native-load cost. This mirrors the
deferral the session recorder and memory store previously implemented inline
and keeps exactly one loading code-path in the project.
"""

from __future__ import annotations

import importlib.metadata
import sqlite3

#: Supported sqlite-vec range — must stay in sync with the ``pyproject.toml`` pin.
SUPPORTED_SQLITE_VEC = ">=0.1.6,<0.2.0"
_MIN_VERSION = (0, 1, 6)
_MAX_VERSION_EXCLUSIVE = (0, 2, 0)


def _installed_version() -> str:
    """Return the installed sqlite-vec version (best effort)."""
    try:
        return importlib.metadata.version("sqlite-vec")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - odd envs
        import sqlite_vec  # type: ignore[import-untyped]

        return str(getattr(sqlite_vec, "__version__", "0"))


def _parse_version(raw: str) -> tuple[int, int, int]:
    """Parse ``"0.1.9"`` → ``(0, 1, 9)``; non-numeric parts count as 0."""
    parts: list[int] = []
    for chunk in raw.split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension on *conn*, enforcing the supported range.

    Raises ``RuntimeError`` when the installed version is outside
    ``SUPPORTED_SQLITE_VEC`` — a version mismatch should fail here, with a
    clear message, instead of surfacing as a wrong result deep in a vector
    query.
    """
    version = _installed_version()
    parsed = _parse_version(version)
    if parsed < _MIN_VERSION or parsed >= _MAX_VERSION_EXCLUSIVE:
        raise RuntimeError(
            f"sqlite-vec {version} is outside the supported range "
            f"{SUPPORTED_SQLITE_VEC}. Run 'uv sync' (or reinstall) so the "
            f"pinned version is used."
        )
    import sqlite_vec

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
