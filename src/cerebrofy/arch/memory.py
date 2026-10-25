"""Warning-memory writes for arch violations (Idea #05 integration).

"Each violation gets a warning memory: 'This rule was violated here — don't
repeat'." Mirrors the coverage-gap/silo/vuln writers: opt-in via
``cerebrofy arch check --write-memories``, deduped by title, capped per run,
and never fatal — memory failures must not break an architecture check.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

from cerebrofy.arch.checker import CheckResult, Violation, fix_hint
from cerebrofy.health.metrics import _lobe_for_file

_MAX_NEW_PER_RUN = 10


def _resolve_neuron_id(index_db: Path, violation: Violation) -> str | None:
    """Find the violating neuron's id in the index DB (best effort)."""
    if not violation.file or not violation.src_name or not index_db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{index_db}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT id FROM nodes WHERE file = ? AND name = ? LIMIT 1",
            (violation.file, violation.src_name),
        ).fetchone()
        return str(row[0]) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def write_violation_memories(
    result: CheckResult,
    cerebrofy_dir: Path,
    lobes: dict[str, str],
    limit: int = _MAX_NEW_PER_RUN,
) -> int:
    """Write one warning memory per violation; returns the number written.

    Error-severity violations are recorded before warnings, titles already
    present as warnings are skipped (repeat checks never spam the store), and
    at most *limit* new memories are written per run. Never raises.
    """
    ordered = list(result.error_violations) + list(result.warning_violations)
    if not ordered:
        return 0

    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.store import Memory, open_memories_db, write_memory

        descriptions = {rr.rule.name: rr.rule.description for rr in result.rule_results}
        index_db = cerebrofy_dir / "db" / "cerebrofy.db"
        mconn = open_memories_db(cerebrofy_dir)
        try:
            existing = {
                str(row[0])
                for row in mconn.execute(
                    "SELECT title FROM memories WHERE type = 'warning'"
                )
            }
            written = 0
            for v in ordered:
                if written >= limit:
                    break
                title = f"Architecture rule '{v.rule_name}' violated at {v.location}"
                if title in existing:
                    continue
                lobe = _lobe_for_file(v.file, lobes) or None
                fix = fix_hint(v.kind, descriptions.get(v.rule_name, ""))
                body = (
                    f"{v.detail}\n\n"
                    "This architecture rule was violated here — don't repeat it.\n"
                    f"Fix: {fix}"
                )
                mem = Memory(
                    id=str(uuid.uuid4()),
                    neuron_id=_resolve_neuron_id(index_db, v),
                    lobe=lobe,
                    type="warning",
                    title=title,
                    body=body,
                    author="agent:arch-check",
                    created_ts=int(time.time()),
                    tags=("arch", v.rule_name),
                    decay_score=1.0,
                    status="active",
                )
                write_memory(mconn, mem, embed_memory(title, body))
                existing.add(title)
                written += 1
            mconn.commit()
            return written
        finally:
            mconn.close()
    except Exception as exc:  # noqa: BLE001
        return 0  # Non-fatal — memory writes never block the check
