"""Changelog evidence loaders: DB access, git output, memory/docstring extraction.

Split from ``generator.py`` (M3); these functions read the index DB and git,
degrading gracefully when evidence sources are absent.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
from pathlib import Path

from cerebrofy.changelog.classifier import ChangelogError
from cerebrofy.constants import DEFAULT_GIT_TIMEOUT_SECONDS
from cerebrofy.errors import NO_INDEX
from cerebrofy.memory.store import Memory
from cerebrofy.memory.store import list_memories as _list_memories
from cerebrofy.memory.store import open_memories_db as _open_memories_db


def _open_index_db(db_path: Path) -> sqlite3.Connection:
    """Open the changelog index DB read-only, or raise NO_INDEX.

    Separated from ``generate_changelog`` so the connection-opening seam is
    independently testable (testability finding #7).
    """
    if not db_path.exists():
        raise ChangelogError(
            NO_INDEX, "Index not found. Run 'cerebrofy build' first."
        )
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _load_memories(cerebrofy_dir: Path) -> dict[str, list[Memory]]:
    """Memories grouped by neuron id; empty mapping when #05 is absent."""
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return {}
    try:
        conn = _open_memories_db(cerebrofy_dir)
        try:
            memories = _list_memories(conn, include_stale=False)
        finally:
            conn.close()
    except Exception:
        return {}

    grouped: dict[str, list[Memory]] = {}
    for memory in memories:
        if memory.neuron_id:
            grouped.setdefault(memory.neuron_id, []).append(memory)
    return grouped


def _health_delta(conn: sqlite3.Connection) -> dict[str, float]:
    """Coupling / avg-blast change between the two newest health snapshots."""
    zero = {"coupling": 0.0, "avg_blast": 0.0}
    try:
        rows = conn.execute(
            "SELECT coupling, avg_blast FROM health_snapshots ORDER BY build_ts DESC LIMIT 2"
        ).fetchall()
    except sqlite3.OperationalError:
        return zero
    if len(rows) < 2:
        return zero
    (cur_c, cur_b), (prev_c, prev_b) = rows[0], rows[1]
    return {
        "coupling": round(float(cur_c or 0.0) - float(prev_c or 0.0), 4),
        "avg_blast": round(float(cur_b or 0.0) - float(prev_b or 0.0), 2),
    }


def _git_output(args: list[str], repo_root: Path) -> str | None:
    """Run *args* via git in *repo_root*; return stdout on success, ``None`` on failure.

    User-supplied refs are validated via ``validate_git_ref`` at call sites; this
    is a defence-in-depth check that allows git option characters in the fixed
    argument list.
    """
    for arg in args:
        if not re.match(r"^[a-zA-Z0-9._/=%-]+$", arg):
            return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _docstrings(conn: sqlite3.Connection) -> dict[str, str]:
    """Map neuron id → docstring for all indexed neurons that have one."""
    try:
        rows = conn.execute(
            "SELECT id, docstring FROM nodes WHERE docstring IS NOT NULL AND docstring != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: row[1] for row in rows}
