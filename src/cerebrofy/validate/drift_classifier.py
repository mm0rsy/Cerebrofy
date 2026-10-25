"""Drift classifier: compare indexed Neurons against current source."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class NeuronDrift:
    """Per-neuron drift detail (name + kind + neuron type) inside one changed file."""

    name: str
    kind: str  # "added" | "removed" | "signature_changed"
    neuron_type: str = ""  # "function" | "class" | "module" | ...


@dataclass(frozen=True)
class DriftRecord:
    file: str
    drift_type: str  # "none" | "minor" | "structural"
    changed_neurons: tuple[str, ...]
    drift_detail: str
    neuron_details: tuple[NeuronDrift, ...] = ()


def _normalize_sig(sig: str) -> str:
    """Eliminate whitespace differences from a signature string."""
    return " ".join(sig.split())


def _get_indexed_neurons(
    conn: sqlite3.Connection, file: str
) -> list[dict[str, str]]:
    """Return list of {name, sig, type} dicts for all indexed Neurons in the given file."""
    rows = conn.execute(
        "SELECT name, signature, type FROM nodes WHERE file = ?", (file,)
    ).fetchall()
    return [
        {"name": name, "sig": _normalize_sig(sig or ""), "type": ntype or ""}
        for name, sig, ntype in rows
    ]


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
    except Exception as exc:  # noqa: BLE001
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
    new_types = {n.name: (n.type or "") for n in pr.neurons}
    indexed = _get_indexed_neurons(conn, file)
    indexed_map = {d["name"]: d["sig"] for d in indexed}
    indexed_types = {d["name"]: d["type"] for d in indexed}

    added = [n for n in new_neurons if n not in indexed_map]
    removed = [n for n in indexed_map if n not in new_neurons]
    sig_changed = [
        n for n in new_neurons
        if n in indexed_map and new_neurons[n] != indexed_map[n]
    ]

    if added or removed or sig_changed:
        changed = tuple(added + removed + sig_changed)
        details = []
        neuron_details: list[NeuronDrift] = []
        for n in added:
            details.append(f"{file}::{n}  [added]")
            neuron_details.append(
                NeuronDrift(name=n, kind="added", neuron_type=new_types.get(n, ""))
            )
        for n in removed:
            details.append(f"{file}::{n}  [removed]")
            neuron_details.append(
                NeuronDrift(name=n, kind="removed", neuron_type=indexed_types.get(n, ""))
            )
        for n in sig_changed:
            details.append(f"{file}::{n}  [signature changed]")
            neuron_details.append(
                NeuronDrift(
                    name=n, kind="signature_changed", neuron_type=new_types.get(n, "")
                )
            )
        return DriftRecord(
            file=file,
            drift_type="structural",
            changed_neurons=changed,
            drift_detail="\n".join(details),
            neuron_details=tuple(neuron_details),
        )

    # File content changed (hash mismatch triggered re-parse) but all Neurons
    # are identical → minor drift (comment / whitespace / formatting only).
    # NOTE: import-level drift is not yet detected here because import statement
    # text is not stored in the DB (requires a dedicated schema migration to add
    # import tracking — tracked as a known gap).
    return DriftRecord(
        file=file,
        drift_type="minor",
        changed_neurons=(),
        drift_detail="non-structural changes only (whitespace/comments)",
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
            # Deleted indexed file: every neuron it had is now "removed" → structural drift.
            rows = conn.execute(
                "SELECT name, type FROM nodes WHERE file = ?", (file,)
            ).fetchall()
            neuron_names = tuple(row[0] for row in rows)
            if neuron_names:
                details = "\n".join(f"{file}::{n}  [removed]" for n in neuron_names)
                records.append(DriftRecord(
                    file=file,
                    drift_type="structural",
                    changed_neurons=neuron_names,
                    drift_detail=details,
                    neuron_details=tuple(
                        NeuronDrift(name=name, kind="removed", neuron_type=ntype or "")
                        for name, ntype in rows
                    ),
                ))
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
