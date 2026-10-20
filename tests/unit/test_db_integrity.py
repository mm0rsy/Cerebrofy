"""Unit tests for db/integrity.py — SHA256 sidecar (S2/n12)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from cerebrofy.db.connection import open_db_readonly
from cerebrofy.db.integrity import (
    compute_db_sha256,
    sidecar_path,
    verify_integrity,
    write_sidecar,
)
from cerebrofy.errors import IntegrityError


def _fake_db(tmp_path: Path, payload: bytes = b"sqlite-ish bytes") -> Path:
    db = tmp_path / "cerebrofy.db"
    db.write_bytes(payload)
    return db


def _real_db(tmp_path: Path) -> Path:
    db = tmp_path / "cerebrofy.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    return db


def test_sidecar_round_trip(tmp_path: Path) -> None:
    db = _fake_db(tmp_path)

    digest = write_sidecar(db)

    assert sidecar_path(db).read_text(encoding="ascii").strip() == digest
    assert compute_db_sha256(db) == digest
    assert verify_integrity(db, "fail") is True


def test_missing_sidecar_is_noop_even_in_fail_mode(tmp_path: Path) -> None:
    """Pre-sidecar databases must stay readable."""
    db = _fake_db(tmp_path)

    assert verify_integrity(db, "fail") is True


def test_off_mode_skips_verification(tmp_path: Path) -> None:
    db = _fake_db(tmp_path)
    write_sidecar(db)
    db.write_bytes(b"tampered")

    assert verify_integrity(db, "off") is True


def test_mismatch_warn_logs_and_returns_false(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = _fake_db(tmp_path)
    write_sidecar(db)
    db.write_bytes(b"tampered")

    with caplog.at_level(logging.WARNING, logger="cerebrofy.db.integrity"):
        assert verify_integrity(db, "warn") is False
    assert "integrity check failed" in caplog.text


def test_mismatch_fail_raises_integrity_error(tmp_path: Path) -> None:
    db = _fake_db(tmp_path)
    write_sidecar(db)
    db.write_bytes(b"tampered")

    with pytest.raises(IntegrityError, match="integrity check failed"):
        verify_integrity(db, "fail")


def test_cache_skips_recompute_when_files_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _fake_db(tmp_path)
    write_sidecar(db)
    assert verify_integrity(db, "warn") is True

    from cerebrofy.db import integrity as mod

    calls = {"count": 0}
    real = mod.compute_db_sha256

    def counting(path: Path) -> str:
        calls["count"] += 1
        return real(path)

    monkeypatch.setattr(mod, "compute_db_sha256", counting)
    assert verify_integrity(db, "warn") is True
    assert calls["count"] == 0


def test_write_sidecar_leaves_no_temp_file(tmp_path: Path) -> None:
    db = _fake_db(tmp_path)

    write_sidecar(db)

    assert list(tmp_path.glob("*.tmp")) == []


def test_open_db_readonly_verifies_and_opens(tmp_path: Path) -> None:
    db = _real_db(tmp_path)
    write_sidecar(db)

    conn = open_db_readonly(db, integrity_check="fail")
    try:
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    finally:
        conn.close()


def test_open_db_readonly_fail_mode_rejects_tampered_db(tmp_path: Path) -> None:
    db = _real_db(tmp_path)
    write_sidecar(db)
    db.write_bytes(b"not a database")

    with pytest.raises(IntegrityError):
        open_db_readonly(db, integrity_check="fail")
