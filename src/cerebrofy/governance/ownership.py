"""Lobe ownership computation for the governance surface (Idea #18).

Ownership can be derived from git blame (default), an explicit
``.cerebrofy/team.yaml`` file, or a hybrid that weights blame by recent commit
activity. The git-blame primitives are the same ones used by the knowledge silo
detector (``cerebrofy.analysis.silo_detector``) so the two surfaces never drift.
"""

from __future__ import annotations

import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cerebrofy.errors import ConfigError, NoGitHistoryError

DEFAULT_ACTIVITY_DAYS = 90
DEFAULT_FALLBACK_OWNER = "@tech-leads"
OWNERSHIP_STRATEGIES: tuple[str, ...] = ("git-blame", "explicit", "hybrid")

_TEAM_FILENAME = "team.yaml"
_GIT_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthorShare:
    """One author's contribution to a lobe."""

    author: str
    lines: int
    score: float
    share: float
    recent_commits: int = 0


@dataclass(frozen=True)
class LobeOwnership:
    """Ownership profile for a single lobe."""

    lobe: str
    strategy: str
    path: str = ""
    authors: tuple[AuthorShare, ...] = ()
    total_lines: int = 0

    @property
    def primary(self) -> str | None:
        """Highest-scoring author, or None when the lobe has no history."""
        return self.authors[0].author if self.authors else None

    @property
    def primary_share(self) -> float:
        return self.authors[0].share if self.authors else 0.0

    @property
    def bus_factor(self) -> int:
        """Number of authors needed to cover more than half of the lobe."""
        cumulative = 0.0
        for index, author in enumerate(self.authors, start=1):
            cumulative += author.share
            if cumulative > 0.5:
                return index
        return len(self.authors)

    @property
    def has_history(self) -> bool:
        return bool(self.authors)

    def top_authors(self, limit: int) -> tuple[AuthorShare, ...]:
        return self.authors[:limit]


@dataclass(frozen=True)
class TeamConfig:
    """Explicit ownership rules parsed from ``.cerebrofy/team.yaml``."""

    lobes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    default_owner: str | None = None


@dataclass(frozen=True)
class CrossLobeCall:
    """Number of call edges flowing from ``caller_lobe`` into a target lobe."""

    caller_lobe: str
    count: int


# ---------------------------------------------------------------------------
# Lobe/file mapping
# ---------------------------------------------------------------------------


def lobe_for_file(file_path: str, lobes: dict[str, str]) -> str:
    """Resolve *file_path* to its configured lobe using the longest path prefix.

    A root lobe (``.`` or empty path) only wins when no more specific path
    matches. Returns ``"__unknown__"`` when nothing matches.
    """
    normalised = file_path.replace("\\", "/")
    ordered = sorted(
        lobes.items(),
        key=lambda item: (-len(item[1].replace("\\", "/").strip("/")), item[0]),
    )
    for name, raw_path in ordered:
        path = raw_path.replace("\\", "/").strip("/")
        if path in ("", "."):
            return name
        if normalised == path or normalised.startswith(path + "/"):
            return name
    return "__unknown__"


def _lobe_files(
    conn: sqlite3.Connection,
    lobes: dict[str, str],
    lobe: str,
) -> dict[str, list[tuple[int, int]]]:
    """Return ``{file: [(line_start, line_end), ...]}`` for *lobe* neurons."""
    rows = conn.execute(
        "SELECT file, line_start, line_end FROM nodes "
        "WHERE file IS NOT NULL AND line_start IS NOT NULL AND type != 'module'"
    ).fetchall()
    files: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for file_path, line_start, line_end in rows:
        if lobe_for_file(str(file_path), lobes) != lobe:
            continue
        start = int(line_start or 1)
        end = int(line_end or start)
        files[str(file_path)].append((start, max(start, end)))
    return dict(files)


# ---------------------------------------------------------------------------
# Team file (explicit strategy)
# ---------------------------------------------------------------------------


def team_path(root: Path) -> Path:
    """Return the conventional explicit-ownership file path."""
    return root / ".cerebrofy" / _TEAM_FILENAME


def load_team_config(root: Path) -> TeamConfig:
    """Load ``.cerebrofy/team.yaml``; returns an empty config when absent.

    Supported shape::

        default_owner: "@tech-leads"
        lobes:
          auth:
            owners: ["alice@co.com", "@alice"]
          graph:
            owners: ["bob@co.com"]
    """
    path = team_path(root)
    if not path.exists():
        return TeamConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level YAML mapping expected")

    default_owner = raw.get("default_owner")
    if default_owner is not None and not isinstance(default_owner, str):
        raise ConfigError(f"{path}: 'default_owner' must be a string")

    raw_lobes = raw.get("lobes") or {}
    if not isinstance(raw_lobes, dict):
        raise ConfigError(f"{path}: 'lobes' must be a mapping")

    parsed: dict[str, tuple[str, ...]] = {}
    for lobe, payload in raw_lobes.items():
        name = str(lobe).strip()
        if not name:
            continue
        owners: Any
        if isinstance(payload, str):
            owners = [payload]
        elif isinstance(payload, list):
            owners = payload
        elif isinstance(payload, dict):
            owners = payload.get("owners", payload.get("owner", []))
            if isinstance(owners, str):
                owners = [owners]
        else:
            raise ConfigError(f"{path}: lobes.{name} must be a list or mapping")
        if not isinstance(owners, list):
            raise ConfigError(f"{path}: lobes.{name}.owners must be a list")
        cleaned = tuple(str(owner).strip() for owner in owners if str(owner).strip())
        parsed[name] = cleaned

    return TeamConfig(
        lobes=parsed,
        default_owner=default_owner.strip() if isinstance(default_owner, str) else None,
    )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _has_git_history(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _blame_counts(
    files: dict[str, list[tuple[int, int]]],
    repo_root: Path,
    blame_cache: dict[str, dict[int, str]] | None = None,
) -> dict[str, int]:
    """Count blamed lines per author across the neuron line ranges of *files*.

    Nested neurons share lines; each physical line is counted at most once per
    file so parent classes and their methods do not double-weight an author.
    """
    from cerebrofy.analysis.silo_detector import _blame_file

    cache = blame_cache if blame_cache is not None else {}
    counts: dict[str, int] = defaultdict(int)
    for file_path in sorted(files):
        if file_path not in cache:
            cache[file_path] = _blame_file(file_path, repo_root)
        line_authors = cache[file_path]
        wanted: set[int] = set()
        for start, end in files[file_path]:
            wanted.update(range(start, end + 1))
        for line in sorted(wanted):
            author = line_authors.get(line)
            if not author or author == "unknown":
                continue
            counts[author] += 1
    return dict(counts)


def _recent_commit_counts(
    files: list[str],
    repo_root: Path,
    activity_days: int,
) -> dict[str, int]:
    """Count commits per author across *files* in the last *activity_days*."""
    if not files:
        return {}
    counts: dict[str, int] = defaultdict(int)
    chunk_size = 50
    for offset in range(0, len(files), chunk_size):
        chunk = files[offset : offset + chunk_size]
        result = subprocess.run(
            [
                "git",
                "log",
                f"--since={activity_days} days ago",
                "--format=%ae",
                "--",
                *chunk,
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT,
        )
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            author = line.strip()
            if author:
                counts[author] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Ownership computation
# ---------------------------------------------------------------------------


def _normalise_authors(
    raw: dict[str, tuple[int, float, int]],
) -> tuple[AuthorShare, ...]:
    total = sum(score for _, score, _ in raw.values())
    if total <= 0:
        return ()
    shares = [
        AuthorShare(
            author=author,
            lines=lines,
            score=round(score, 4),
            share=round(score / total, 4),
            recent_commits=recent,
        )
        for author, (lines, score, recent) in raw.items()
    ]
    shares.sort(key=lambda item: (-item.score, item.author))
    return tuple(shares)


def _explicit_ownership(lobe: str, path: str, team: TeamConfig) -> LobeOwnership:
    owners = team.lobes.get(lobe, ())
    if not owners and team.default_owner:
        owners = (team.default_owner,)
    if not owners:
        return LobeOwnership(lobe=lobe, strategy="explicit", path=path)
    share = round(1.0 / len(owners), 4)
    authors = tuple(
        AuthorShare(author=owner, lines=0, score=1.0, share=share) for owner in owners
    )
    return LobeOwnership(
        lobe=lobe,
        strategy="explicit",
        path=path,
        authors=authors,
        total_lines=0,
    )


def compute_lobe_ownership(
    conn: sqlite3.Connection,
    repo_root: Path,
    lobes: dict[str, str],
    lobe: str,
    *,
    strategy: str = "git-blame",
    activity_days: int = DEFAULT_ACTIVITY_DAYS,
    team: TeamConfig | None = None,
    blame_cache: dict[str, dict[int, str]] | None = None,
) -> LobeOwnership:
    """Compute author shares for *lobe* using the requested strategy."""
    if lobe not in lobes:
        raise ValueError(f"Unknown lobe '{lobe}' — not present in .cerebrofy/config.yaml")
    if strategy not in OWNERSHIP_STRATEGIES:
        raise ValueError(
            f"Unknown ownership strategy '{strategy}' — expected one of "
            f"{', '.join(OWNERSHIP_STRATEGIES)}"
        )

    path = lobes[lobe]
    if strategy == "explicit":
        return _explicit_ownership(lobe, path, team or load_team_config(repo_root))

    if not _has_git_history(repo_root):
        raise NoGitHistoryError(
            f"Repository at {repo_root} has no git commit history — "
            "cannot compute '{strategy}' ownership."
        )

    files = _lobe_files(conn, lobes, lobe)
    blame_counts = _blame_counts(files, repo_root, blame_cache)
    if not blame_counts:
        return LobeOwnership(lobe=lobe, strategy=strategy, path=path)

    recent: dict[str, int] = {}
    if strategy == "hybrid":
        recent = _recent_commit_counts(sorted(files), repo_root, activity_days)
    recent_total = sum(recent.values())

    raw: dict[str, tuple[int, float, int]] = {}
    for author, lines in blame_counts.items():
        commits = recent.get(author, 0)
        if strategy == "hybrid" and recent_total:
            # Recent activity can boost an author by at most 50%.
            score = lines * (1.0 + 0.5 * (commits / recent_total))
        else:
            score = float(lines)
        raw[author] = (lines, score, commits)

    authors = _normalise_authors(raw)
    return LobeOwnership(
        lobe=lobe,
        strategy=strategy,
        path=path,
        authors=authors,
        total_lines=sum(blame_counts.values()),
    )


def compute_all_lobe_ownership(
    conn: sqlite3.Connection,
    repo_root: Path,
    lobes: dict[str, str],
    *,
    strategy: str = "git-blame",
    activity_days: int = DEFAULT_ACTIVITY_DAYS,
    team: TeamConfig | None = None,
) -> dict[str, LobeOwnership]:
    """Compute ownership for every configured lobe, sharing the blame cache."""
    effective_team = team if team is not None else load_team_config(repo_root)
    blame_cache: dict[str, dict[int, str]] = {}
    return {
        lobe: compute_lobe_ownership(
            conn,
            repo_root,
            lobes,
            lobe,
            strategy=strategy,
            activity_days=activity_days,
            team=effective_team,
            blame_cache=blame_cache,
        )
        for lobe in sorted(lobes)
    }


# ---------------------------------------------------------------------------
# Graph-derived governance context
# ---------------------------------------------------------------------------


def _node_lobes(conn: sqlite3.Connection, lobes: dict[str, str]) -> dict[str, str]:
    rows = conn.execute("SELECT id, file FROM nodes").fetchall()
    return {
        str(node_id): lobe_for_file(str(file_path), lobes)
        for node_id, file_path in rows
        if file_path is not None
    }


def cross_lobe_callers(
    conn: sqlite3.Connection,
    lobes: dict[str, str],
) -> dict[str, tuple[CrossLobeCall, ...]]:
    """Map each lobe to the other lobes that call into it, by edge count.

    RUNTIME_BOUNDARY edges are excluded (Law II). Cross-lobe edges are also the
    data source for CODEOWNERS co-reviewers and secondary reviewer suggestions.
    """
    from cerebrofy.graph.edges import RUNTIME_BOUNDARY

    node_lobe = _node_lobes(conn, lobes)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for src_id, dst_id, rel_type in conn.execute(
        "SELECT src_id, dst_id, rel_type FROM edges"
    ):
        if rel_type == RUNTIME_BOUNDARY:
            continue
        src_lobe = node_lobe.get(str(src_id))
        dst_lobe = node_lobe.get(str(dst_id))
        if not src_lobe or not dst_lobe or src_lobe == dst_lobe:
            continue
        if src_lobe == "__unknown__" or dst_lobe == "__unknown__":
            continue
        counts[dst_lobe][src_lobe] += 1
    return {
        target: tuple(
            CrossLobeCall(caller_lobe=caller, count=count)
            for caller, count in sorted(
                callers.items(), key=lambda item: (-item[1], item[0])
            )
        )
        for target, callers in counts.items()
    }


def in_adjacency(conn: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """Build the reverse caller graph with RUNTIME_BOUNDARY edges excluded."""
    from cerebrofy.graph.edges import RUNTIME_BOUNDARY

    known = {
        str(row[0]) for row in conn.execute("SELECT id FROM nodes").fetchall()
    }
    incoming: dict[str, set[str]] = defaultdict(set)
    for src_id, dst_id, rel_type in conn.execute(
        "SELECT src_id, dst_id, rel_type FROM edges"
    ):
        if rel_type == RUNTIME_BOUNDARY:
            continue
        src = str(src_id)
        dst = str(dst_id)
        if src in known and dst in known:
            incoming[dst].add(src)
    return {dst: tuple(sorted(srcs)) for dst, srcs in incoming.items()}


def max_blast_radius(
    conn: sqlite3.Connection,
    lobes: dict[str, str],
    *,
    lobe: str | None = None,
    changed_files: frozenset[str] | None = None,
) -> int:
    """Largest depth-1 + depth-2 caller count among the selected neurons."""
    from cerebrofy.analysis.blast_radius import caller_ids_within_depth2

    adjacency = in_adjacency(conn)
    rows = conn.execute(
        "SELECT id, file FROM nodes WHERE type != 'module' AND file IS NOT NULL"
    ).fetchall()
    highest = 0
    for node_id, file_path in rows:
        file = str(file_path)
        if changed_files is not None and file not in changed_files:
            continue
        if lobe is not None and lobe_for_file(file, lobes) != lobe:
            continue
        radius = len(caller_ids_within_depth2(str(node_id), adjacency))
        highest = max(highest, radius)
    return highest


def recent_contributors(
    conn: sqlite3.Connection,
    repo_root: Path,
    lobes: dict[str, str],
    lobe: str,
    *,
    activity_days: int = DEFAULT_ACTIVITY_DAYS,
    limit: int = 5,
) -> tuple[tuple[str, int], ...]:
    """Authors with the most commits touching *lobe* in the activity window."""
    files = sorted(_lobe_files(conn, lobes, lobe))
    counts = _recent_commit_counts(files, repo_root, activity_days)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(ordered[:limit])
