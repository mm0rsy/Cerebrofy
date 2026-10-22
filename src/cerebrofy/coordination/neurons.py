"""Neuron-id expansion shared by the coordination CLI and MCP tools (Idea #25).

A claim target is either a literal neuron id (``file::name``) or a file path.
The IDEA requires a file path to expand to every neuron indexed for that file,
whether the claim is made through the CLI or through an MCP tool. Keeping the
implementation here prevents the two surfaces from drifting.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

_INDEX_RELATIVE = Path(".cerebrofy") / "db" / "cerebrofy.db"


def repo_relative(root: Path, token: str) -> str:
    """Normalise a claim token to a forward-slash repo-relative path."""
    candidate = Path(token)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return token.replace("\\", "/")
    normalised = token.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def expand_neurons(root: Path, tokens: Sequence[str]) -> list[str]:
    """Expand file-path tokens into every neuron indexed for that file.

    Tokens containing ``::`` are literal neuron ids. A path that is absent from
    the index falls back to the literal token so the claim still surfaces a
    useful identifier. The index is opened read-only; a missing or unreadable
    database degrades to literal tokens rather than raising.
    """
    db_path = root / _INDEX_RELATIVE
    conn: sqlite3.Connection | None = None
    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            conn = None

    expanded: list[str] = []
    try:
        for token in tokens:
            if "::" in token or conn is None:
                expanded.append(token)
                continue
            try:
                rows = conn.execute(
                    "SELECT id FROM nodes WHERE file = ?",
                    (repo_relative(root, token),),
                ).fetchall()
            except sqlite3.Error:
                rows = []
            if rows:
                expanded.extend(str(row[0]) for row in rows)
            else:
                expanded.append(token)
    finally:
        if conn is not None:
            conn.close()

    return list(dict.fromkeys(expanded))
