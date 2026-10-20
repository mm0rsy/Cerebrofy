"""At-rest integrity sidecar for cerebrofy.db (Wave A S2 / n12).

``cerebrofy build`` / ``cerebrofy update`` write a ``<db>.sha256`` sidecar
after their final database writes; read paths verify the digest and react
according to the ``database.integrity_check`` config:

* ``off``  — never read the sidecar;
* ``warn`` — log a warning on mismatch (default);
* ``fail`` — raise :class:`~cerebrofy.errors.IntegrityError` on mismatch.

A *missing* sidecar is a no-op, so databases built before this feature (or
without a completed build/update) remain readable. Verification is best-effort
against at-rest tampering: WAL checkpoints and concurrent writers can
legitimately change file bytes between the hash and a read, which is why the
default mode only warns. See ``docs/security.md``.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from cerebrofy.errors import IntegrityError

_logger = logging.getLogger(__name__)

_SIDECAR_SUFFIX = ".sha256"
_CHUNK_SIZE = 1024 * 1024  # 1 MiB

#: Result cache keyed by the sidecar path → ((db fingerprint, sidecar
#: fingerprint), ok). The fingerprints are ``(st_mtime_ns, st_size)`` pairs, so
#: any rebuild naturally invalidates the entry without explicit bookkeeping.
_CACHE: dict[Path, tuple[tuple[tuple[int, int], tuple[int, int] | None], bool]] = {}


def sidecar_path(db_path: Path) -> Path:
    """Return the ``<db>.sha256`` sidecar path for *db_path*."""
    return db_path.with_name(db_path.name + _SIDECAR_SUFFIX)


def compute_db_sha256(db_path: Path) -> str:
    """Streaming SHA256 of the database file (never loads it into memory)."""
    digest = hashlib.sha256()
    with db_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sidecar(db_path: Path) -> str:
    """Write the digest sidecar atomically; return the digest.

    Call this only **after** the final database writes and after the writing
    connection is closed, so WAL frames have been checkpointed into the main
    file before it is hashed.
    """
    digest = compute_db_sha256(db_path)
    target = sidecar_path(db_path)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(digest + "\n", encoding="ascii")
    os.replace(str(tmp), str(target))
    _CACHE.pop(target, None)
    return digest


def _fingerprints(db_path: Path, side: Path) -> tuple[tuple[int, int], tuple[int, int] | None]:
    db_stat = db_path.stat()
    db_fp = (db_stat.st_mtime_ns, db_stat.st_size)
    try:
        side_stat = side.stat()
    except OSError:
        return db_fp, None
    return db_fp, (side_stat.st_mtime_ns, side_stat.st_size)


def verify_integrity(db_path: Path, mode: str = "warn") -> bool:
    """Verify *db_path* against its SHA256 sidecar.

    Returns ``True`` when the database matches (or the check was skipped) and
    ``False`` when a mismatch was only *warned* about; in ``fail`` mode a
    mismatch raises :class:`~cerebrofy.errors.IntegrityError` instead.
    """
    if mode == "off" or not db_path.exists():
        return True

    side = sidecar_path(db_path)
    if not side.exists():
        return True  # pre-sidecar database: nothing to verify

    fingerprint = _fingerprints(db_path, side)
    cached = _CACHE.get(side)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]

    expected = side.read_text(encoding="ascii").strip()
    actual = compute_db_sha256(db_path)
    ok = bool(expected) and expected == actual
    if not ok:
        message = (
            f"Database integrity check failed for {db_path}: the SHA256 sidecar "
            f"does not match the file (sidecar {expected or 'empty'}, actual "
            f"{actual}). If the change was not intentional, rebuild with "
            f"'cerebrofy build'."
        )
        if mode == "fail":
            raise IntegrityError(message)
        _logger.warning("%s", message)
    _CACHE[side] = (fingerprint, ok)
    return ok
