"""Build lock — PID-based lock file to prevent concurrent builds."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildLock:
    lock_path: Path
    pid: int


def acquire(lock_path: Path) -> BuildLock:
    """Write current PID to lock_path and return a BuildLock."""
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    return BuildLock(lock_path=lock_path, pid=os.getpid())


def release(lock: BuildLock) -> None:
    """Delete the lock file if it exists (idempotent)."""
    try:
        lock.lock_path.unlink()
    except FileNotFoundError:
        pass


def is_stale(lock_path: Path) -> bool:
    """Return True if lock_path exists but the owning process is dead."""
    if not lock_path.exists():
        return False
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return True  # Corrupt lock file — treat as stale
    try:
        os.kill(pid, 0)
    except OSError:
        return True  # Process is dead
    return False
