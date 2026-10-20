"""Unit tests for db/vec.py — sqlite-vec version guard (S2/n11)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrofy.db import vec as vec_mod


def test_parse_version_handles_plain_and_partial_versions() -> None:
    assert vec_mod._parse_version("0.1.9") == (0, 1, 9)
    assert vec_mod._parse_version("0.2.0") == (0, 2, 0)
    assert vec_mod._parse_version("0.1") == (0, 1, 0)
    assert vec_mod._parse_version("1") == (1, 0, 0)


def test_load_sqlite_vec_accepts_installed_version() -> None:
    conn = sqlite3.connect(":memory:")

    vec_mod.load_sqlite_vec(conn)

    assert conn.execute("SELECT vec_version()").fetchone()[0]


@pytest.mark.parametrize("version", ["0.2.0", "0.3.1", "0.1.5", "0.0.9"])
def test_load_sqlite_vec_rejects_versions_outside_range(
    version: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vec_mod, "_installed_version", lambda: version)
    conn = sqlite3.connect(":memory:")

    with pytest.raises(RuntimeError, match="outside the supported range"):
        vec_mod.load_sqlite_vec(conn)


def test_supported_range_matches_pyproject_pin() -> None:
    """The runtime guard and the pyproject pin must not drift apart."""
    root = Path(__file__).parents[2]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert f'"sqlite-vec{vec_mod.SUPPORTED_SQLITE_VEC}",' in text
