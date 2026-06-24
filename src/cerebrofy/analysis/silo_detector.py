"""Knowledge silo detector: git blame × call graph = bus factor risk per neuron."""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SiloNeuron:
    """Risk profile for a single neuron with knowledge concentration data."""

    id: str
    name: str
    file: str
    line_start: int
    line_end: int
    lobe: str
    unique_authors: int
    primary_author: str
    primary_author_pct: float  # 0–1: fraction of lines owned by primary author
    caller_count: int           # depth-1 + depth-2 callers from BFS
    silo_score: float           # caller_count / unique_authors (higher = more dangerous)
    risk_label: str             # LOW / MEDIUM / HIGH / CRITICAL
    risk_icon: str


@dataclass
class SiloReport:
    """Full knowledge silo report across all indexed neurons."""

    neurons: list[SiloNeuron] = field(default_factory=list)
    total_neurons_scanned: int = 0
    silos_detected: int = 0         # neurons with unique_authors == 1
    as_of_commit: str | None = None


# ---------------------------------------------------------------------------
# Git blame helpers
# ---------------------------------------------------------------------------

def _get_current_commit(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo_root), capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def _blame_file(file_path: str, repo_root: Path) -> dict[int, str]:
    """Return {final_line_number: author_email} for every line in file_path.

    Uses git blame --porcelain. Skips files outside the repo or with no commits.
    """
    result = subprocess.run(
        ["git", "blame", "--porcelain", "--", file_path],
        cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}

    commit_emails: dict[str, str] = {}
    current_commit: str = ""
    current_final_line: int = 0
    line_authors: dict[int, str] = {}

    for line in result.stdout.splitlines():
        if line.startswith("\t"):
            if current_commit and current_final_line:
                email = commit_emails.get(current_commit, "unknown")
                line_authors[current_final_line] = email
        elif line.startswith("author-mail "):
            email = line[len("author-mail "):].strip().strip("<>")
            if current_commit:
                commit_emails[current_commit] = email
        else:
            parts = line.split(" ")
            if (
                len(parts) >= 3
                and len(parts[0]) == 40
                and all(c in "0123456789abcdef" for c in parts[0])
            ):
                current_commit = parts[0]
                try:
                    current_final_line = int(parts[2])
                except ValueError:
                    current_final_line = 0

    return line_authors


def _authors_for_range(
    line_authors: dict[int, str], line_start: int, line_end: int
) -> tuple[set[str], str, float]:
    """Return (unique_authors, primary_author, primary_author_pct) for a line range.

    Falls back gracefully when blame data is missing.
    """
    lines = [
        line_authors[ln]
        for ln in range(line_start, (line_end or line_start) + 1)
        if ln in line_authors
    ]
    if not lines:
        return {"unknown"}, "unknown", 1.0

    author_counts: dict[str, int] = {}
    for a in lines:
        author_counts[a] = author_counts.get(a, 0) + 1

    primary = max(author_counts, key=lambda a: author_counts[a])
    pct = author_counts[primary] / max(len(lines), 1)
    return set(author_counts), primary, round(pct, 3)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _silo_risk_label(score: float) -> str:
    if score >= 20.0:
        return "CRITICAL"
    if score >= 8.0:
        return "HIGH"
    if score >= 3.0:
        return "MEDIUM"
    return "LOW"


def _silo_risk_icon(label: str) -> str:
    return {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(label, "⚪")


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_silo_report(
    conn: sqlite3.Connection,
    repo_root: Path,
    depth: int = 2,
    min_callers: int = 1,
    top: int = 50,
) -> SiloReport:
    """Compute knowledge silo risk for all neurons.

    Algorithm:
      1. Fetch all neurons with line ranges from the index.
      2. For each unique file, run git blame once and build a line→author map.
      3. For each neuron, compute unique_authors from its line range.
      4. Run BFS to count callers at depth 1+2.
      5. silo_score = caller_count / unique_authors.
      6. Filter to min_callers, sort by silo_score desc, return top N.
    """
    from cerebrofy.analysis.blast_radius import bfs_callers

    # Fetch all neurons with file and line info
    rows = conn.execute(
        "SELECT id, name, file, line_start, line_end FROM nodes ORDER BY file, line_start"
    ).fetchall()

    # Build blame cache: file → {line: email}
    blame_cache: dict[str, dict[int, str]] = {}
    for _, _, file_path, _, _ in rows:
        if file_path and file_path not in blame_cache:
            blame_cache[file_path] = _blame_file(file_path, repo_root)

    # Resolve lobe per file (dirname of file relative to repo root)
    def _lobe(file_path: str) -> str:
        parts = Path(file_path).parts
        return parts[0] if parts else "root"

    results: list[SiloNeuron] = []
    for neuron_id, name, file_path, line_start, line_end in rows:
        if not file_path or not line_start:
            continue

        # Authors for this neuron's line range
        file_blame = blame_cache.get(file_path, {})
        unique_authors, primary_author, primary_pct = _authors_for_range(
            file_blame, line_start or 1, line_end or line_start or 1
        )

        # BFS caller count
        d1, d2, _ = bfs_callers(neuron_id, conn, max_depth=depth)
        caller_count = len(d1) + len(d2)

        if caller_count < min_callers:
            continue

        n_authors = len(unique_authors)
        silo_score = round(caller_count / max(n_authors, 1), 2)
        label = _silo_risk_label(silo_score)

        results.append(SiloNeuron(
            id=neuron_id,
            name=name,
            file=file_path,
            line_start=line_start,
            line_end=line_end or line_start,
            lobe=_lobe(file_path),
            unique_authors=n_authors,
            primary_author=primary_author,
            primary_author_pct=primary_pct,
            caller_count=caller_count,
            silo_score=silo_score,
            risk_label=label,
            risk_icon=_silo_risk_icon(label),
        ))

    results.sort(key=lambda n: n.silo_score, reverse=True)
    top_results = results[:top]

    return SiloReport(
        neurons=top_results,
        total_neurons_scanned=len(rows),
        silos_detected=sum(1 for r in results if r.unique_authors == 1),
        as_of_commit=_get_current_commit(repo_root),
    )
