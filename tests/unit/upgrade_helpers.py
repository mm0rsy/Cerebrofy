"""Shared fixtures/helpers for Upgrade Navigator unit tests (not collected)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cerebrofy.db.schema import create_schema


def make_index_repo(
    root: Path,
    files: dict[str, str],
    nodes: list[tuple[str, str, str, str, int, int]],
    edges: list[tuple[str, str, str, str]] | None = None,
) -> Path:
    """Create source files plus a real-schema cerebrofy.db under *root*.

    ``nodes`` rows are ``(id, name, file, type, line_start, line_end)``.
    """
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    config_dir = root / ".cerebrofy"
    db_dir = config_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        "lobes:\n  root: .\ntracked_extensions: [.py]\nembedding_model: local\n",
        encoding="utf-8",
    )
    db_path = db_dir / "cerebrofy.db"
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn, 0)
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
        conn.executemany(
            "INSERT INTO nodes(id, name, file, type, line_start, line_end) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            nodes,
        )
        if edges:
            conn.executemany(
                "INSERT INTO edges(src_id, dst_id, rel_type, file) VALUES (?, ?, ?, ?)",
                edges,
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
