"""Compute epistemic confidence and staleness state from an open cerebrofy.db."""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpistemicState:
    graph_age_hours: float
    neurons_changed_since_build: int
    unindexed_languages: tuple[str, ...]
    dynamic_dispatch_count: int
    memory_stale_count: int          # always 0 until Idea #05 is built
    missing_test_paths: int
    overall_confidence: float        # 0.5–1.0
    caveats: tuple[str, ...]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "overall_confidence": self.overall_confidence,
            "graph_age_hours": self.graph_age_hours,
            "neurons_changed_since_build": self.neurons_changed_since_build,
            "unindexed_languages": list(self.unindexed_languages),
            "dynamic_dispatch_count": self.dynamic_dispatch_count,
            "memory_stale_count": self.memory_stale_count,
            "missing_test_paths": self.missing_test_paths,
            "caveats": list(self.caveats),
            "recommendation": self.recommendation,
        }
        if self.overall_confidence < 0.5:
            d["error"] = "STALE DATA — strongly recommend rebuild before acting"
        elif self.overall_confidence < 0.7:
            d["warning"] = "LOW CONFIDENCE — results may be incomplete"
        return d

    def confidence_line(self) -> str:
        pct = int(self.overall_confidence * 100)
        if self.overall_confidence < 0.7:
            suffix = " ⚠️" if self.overall_confidence >= 0.5 else " 🔴"
            return f"[confidence: {pct}% — WARNING: {self.caveats[0]}]{suffix}" if self.caveats else f"[confidence: {pct}%]{suffix}"
        return f"[confidence: {pct}% ✅]"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_epistemic_state(
    conn: sqlite3.Connection,
    tracked_extensions: list[str],
    repo_root: Path,
) -> EpistemicState:
    """Compute epistemic state from an open (read-only or read-write) DB connection."""
    graph_age_hours = _graph_age_hours(conn)
    total_neurons = _total_neurons(conn)
    neurons_changed = _neurons_changed_since_build(conn, repo_root)
    unindexed = _unindexed_languages(conn, tracked_extensions, repo_root)
    dispatch_count = _dynamic_dispatch_count(conn)
    missing_tests = _missing_test_paths(conn)

    age_f = max(0.5, 1.0 - graph_age_hours / 168.0)
    change_f = max(0.5, 1.0 - neurons_changed / max(total_neurons, 1))
    lang_f = max(0.5, 1.0 - 0.1 * len(unindexed))
    dispatch_f = 0.9 if dispatch_count > 0 else 1.0

    confidence = round(age_f * change_f * lang_f * dispatch_f, 3)
    confidence = max(0.5, min(1.0, confidence))

    caveats = _build_caveats(
        graph_age_hours, neurons_changed, total_neurons,
        unindexed, dispatch_count, missing_tests,
    )
    recommendation = _recommendation(confidence, graph_age_hours, neurons_changed)

    return EpistemicState(
        graph_age_hours=round(graph_age_hours, 1),
        neurons_changed_since_build=neurons_changed,
        unindexed_languages=tuple(unindexed),
        dynamic_dispatch_count=dispatch_count,
        memory_stale_count=0,
        missing_test_paths=missing_tests,
        overall_confidence=confidence,
        caveats=tuple(caveats),
        recommendation=recommendation,
    )


# ---------------------------------------------------------------------------
# Sub-computations
# ---------------------------------------------------------------------------

def _graph_age_hours(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT value FROM meta WHERE key = 'last_build'").fetchone()
    if row is None:
        return 0.0
    try:
        ts_str: str = row[0]
        # Stored as "2026-06-21T01:23:45Z"
        dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - dt).total_seconds() / 3600.0
    except Exception:
        return 0.0


def _total_neurons(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
    return int(row[0]) if row else 0


def _neurons_changed_since_build(conn: sqlite3.Connection, repo_root: Path) -> int:
    """Count indexed neurons whose source file has changed since the last build.

    Uses git to detect changed tracked files, then counts neurons in those files.
    Falls back to zero on any git failure (non-git repos, detached HEADs, etc.).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-u"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return 0
        changed_files: set[str] = set()
        for line in result.stdout.splitlines():
            if len(line) >= 4:
                path = line[3:].strip()
                # Handle renamed files (old -> new)
                if " -> " in path:
                    path = path.split(" -> ")[-1]
                changed_files.add(path)
        if not changed_files:
            return 0
        # Count neurons in changed files
        placeholders = ",".join("?" * len(changed_files))
        row = conn.execute(
            f"SELECT COUNT(*) FROM nodes WHERE file IN ({placeholders})",
            list(changed_files),
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _unindexed_languages(
    conn: sqlite3.Connection,
    tracked_extensions: list[str],
    repo_root: Path,
) -> list[str]:
    """Return file extensions present in the repo but not in tracked_extensions."""
    indexed_set = {ext.lstrip(".").lower() for ext in tracked_extensions}
    # Collect extensions from the indexed files (only care about what's actually in the repo)
    known_code_extensions = {
        "ts", "tsx", "js", "jsx", "java", "kt", "go", "rs", "cpp", "c",
        "cs", "rb", "php", "swift", "scala", "r", "dart", "lua",
    }
    found: set[str] = set()
    try:
        for entry in repo_root.rglob("*"):
            if not entry.is_file():
                continue
            ext = entry.suffix.lstrip(".").lower()
            if ext in known_code_extensions and ext not in indexed_set:
                found.add(ext)
                if len(found) >= 10:  # cap scan to avoid slow traversal
                    break
    except Exception:
        pass
    return sorted(found)


_DYNAMIC_PATTERNS = ("getattr", "__dict__", "vars(", "locals(", "globals(", "importlib")


def _dynamic_dispatch_count(conn: sqlite3.Connection) -> int:
    """Count neurons whose signature or docstring contains dynamic dispatch patterns."""
    rows = conn.execute("SELECT signature, docstring FROM nodes").fetchall()
    count = 0
    for sig, doc in rows:
        text = (sig or "") + " " + (doc or "")
        if any(p in text for p in _DYNAMIC_PATTERNS):
            count += 1
    return count


def _missing_test_paths(conn: sqlite3.Connection) -> int:
    """Count non-test neurons not reachable via BFS from any test neuron."""
    nodes = conn.execute("SELECT id, file FROM nodes").fetchall()
    if not nodes:
        return 0

    node_files: dict[str, str] = {row[0]: row[1] for row in nodes}
    edges = conn.execute(
        "SELECT src_id, dst_id FROM edges WHERE rel_type != 'RUNTIME_BOUNDARY'"
    ).fetchall()

    out_adj: dict[str, list[str]] = {}
    for nid in node_files:
        out_adj[nid] = []
    for src, dst in edges:
        if src in node_files and dst in node_files:
            out_adj.setdefault(src, []).append(dst)

    def is_test(file: str) -> bool:
        base = os.path.basename(file)
        return base.startswith("test_") or base.endswith("_test.py")

    test_ids = {nid for nid, f in node_files.items() if is_test(f)}
    non_test_ids = set(node_files) - test_ids

    reachable: set[str] = set()
    frontier = set(test_ids)
    while frontier:
        nxt: set[str] = set()
        for nid in frontier:
            for dst in out_adj.get(nid, []):
                if dst in non_test_ids and dst not in reachable:
                    reachable.add(dst)
                    nxt.add(dst)
        frontier = nxt

    return len(non_test_ids) - len(reachable)


def _build_caveats(
    age_hours: float,
    neurons_changed: int,
    total_neurons: int,
    unindexed: list[str],
    dispatch_count: int,
    missing_tests: int,
) -> list[str]:
    caveats = []
    if age_hours > 1:
        h = int(age_hours)
        suffix = f" — {neurons_changed} neuron(s) changed" if neurons_changed else ""
        caveats.append(f"Graph is {h}h old{suffix}")
    if neurons_changed > 0:
        pct = round(neurons_changed / max(total_neurons, 1) * 100, 1)
        caveats.append(f"{neurons_changed} neuron(s) changed since last build ({pct}% of index)")
    if unindexed:
        caveats.append(
            f"Unindexed language(s): {', '.join(unindexed)} — cross-language calls invisible"
        )
    if dispatch_count > 0:
        caveats.append(
            f"{dispatch_count} dynamic dispatch pattern(s) detected — some callers may be hidden"
        )
    if missing_tests > 0:
        caveats.append(f"{missing_tests} neuron(s) unreachable from any test entry point")
    return caveats


def _recommendation(confidence: float, age_hours: float, neurons_changed: int) -> str:
    if confidence < 0.5:
        return "Run `cerebrofy build` immediately — data is stale and results are unreliable"
    if confidence < 0.7:
        if neurons_changed > 0:
            return "Run `cerebrofy update` to re-index changed files before acting on these results"
        return "Run `cerebrofy build` for full confidence"
    if age_hours > 24:
        return "Consider running `cerebrofy update` to refresh the index"
    return "Index is fresh — results are reliable"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def inject_epistemic(response_text: str, state: EpistemicState) -> str:
    """Inject epistemic dict into a JSON response string, or append a confidence line to text."""
    try:
        data = json.loads(response_text)
        if isinstance(data, dict):
            data["epistemic"] = state.to_dict()
            return json.dumps(data, indent=2)
    except (json.JSONDecodeError, ValueError):
        pass
    # Non-JSON (markdown / plain text): append confidence line
    return response_text.rstrip() + f"\n\n---\nCerebrofy — {state.confidence_line()}\n"
