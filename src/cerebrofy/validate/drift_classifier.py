"""Drift classifier: compare indexed Neurons against current source."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class DriftRecord:
    file: str
    drift_type: str  # "none" | "minor" | "structural"
    changed_neurons: tuple[str, ...]
    drift_detail: str


def _normalize_sig(sig: str) -> str:
    """Eliminate whitespace differences from a signature string."""
    return " ".join(sig.split())


def _get_indexed_neurons(
    conn: sqlite3.Connection, file: str
) -> list[dict[str, str]]:
    """Return list of {name, sig} dicts for all indexed Neurons in the given file."""
    rows = conn.execute(
        "SELECT name, signature FROM nodes WHERE file = ?", (file,)
    ).fetchall()
    return [{"name": name, "sig": _normalize_sig(sig or "")} for name, sig in rows]


def _classify_file_drift(
    file: str,
    conn: sqlite3.Connection,
    config: object,
    repo_root: object,
) -> DriftRecord:
    """Re-parse file, diff against indexed Neurons, return DriftRecord."""
    from pathlib import Path

    from cerebrofy.parser.engine import parse_file

    root: Path = repo_root  # type: ignore[assignment]
    queries_dir = root / ".cerebrofy" / "queries"

    try:
        pr = parse_file(root / file, queries_dir, root)
    except Exception as exc:
        print(
            f"Warning: Syntax error in {file} during validation. Results may be incomplete: {exc}",
            file=sys.stderr,
        )
        return DriftRecord(
            file=file,
            drift_type="minor",
            changed_neurons=(),
            drift_detail=f"parse error: {exc}",
        )

    new_neurons = {
        n.name: _normalize_sig(n.signature or "") for n in pr.neurons
    }
    indexed = _get_indexed_neurons(conn, file)
    indexed_map = {d["name"]: d["sig"] for d in indexed}

    added = [n for n in new_neurons if n not in indexed_map]
    removed = [n for n in indexed_map if n not in new_neurons]
    sig_changed = [
        n for n in new_neurons
        if n in indexed_map and new_neurons[n] != indexed_map[n]
    ]

    if added or removed or sig_changed:
        changed = tuple(added + removed + sig_changed)
        details = []
        for n in added:
            details.append(f"{file}::{n}  [added]")
        for n in removed:
            details.append(f"{file}::{n}  [removed]")
        for n in sig_changed:
            details.append(f"{file}::{n}  [signature changed]")
        return DriftRecord(
            file=file,
            drift_type="structural",
            changed_neurons=changed,
            drift_detail="\n".join(details),
        )

    return DriftRecord(
        file=file,
        drift_type="none",
        changed_neurons=(),
        drift_detail="",
    )


def classify_drift(
    changed_files: list[str],
    conn: sqlite3.Connection,
    config: object,
    repo_root: object,
) -> list[DriftRecord]:
    """Classify drift for each changed file, skipping hash-matching files.

    Returns DriftRecord list for all truly drifted files.
    """
    import hashlib
    from pathlib import Path

    root: Path = repo_root  # type: ignore[assignment]
    records: list[DriftRecord] = []

    for file in changed_files:
        file_path = root / file
        if not file_path.exists():
            # Deleted file — skip (no content to parse)
            continue
        # Hash check: skip if file content matches indexed hash
        current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        row = conn.execute(
            "SELECT hash FROM file_hashes WHERE file = ?", (file,)
        ).fetchone()
        if row and row[0] == current_hash:
            continue  # Unchanged content — no drift possible

        record = _classify_file_drift(file, conn, config, repo_root)
        if record.drift_type != "none":
            records.append(record)

    return records
