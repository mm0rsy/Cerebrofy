"""Reviewer suggestions and change-set helpers for governance (Idea #18).

Reviewer selection combines three signals:

* the primary owner of every changed lobe (git blame / team.yaml / hybrid);
* owners of lobes connected to a changed lobe by cross-lobe call edges;
* recent contributors as a backup when the primary owner is unavailable.

PR mode shells out to the GitHub CLI read-only; diff mode shells out to local
git. Neither path writes to the repository.
"""

from __future__ import annotations

import importlib
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.errors import GitHubNotAuthenticatedError
from cerebrofy.governance.ownership import (
    DEFAULT_ACTIVITY_DAYS,
    CrossLobeCall,
    LobeOwnership,
    TeamConfig,
    compute_all_lobe_ownership,
    cross_lobe_callers,
    load_team_config,
    lobe_for_file,
    recent_contributors,
)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_GIT_TIMEOUT = 30
_GH_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewNeuron:
    """A neuron introduced by the change set (or in a newly-added file)."""

    id: str
    name: str
    file: str


@dataclass(frozen=True)
class ChangeSet:
    """Files and added line ranges describing a PR or local diff."""

    source: str  # "diff" | "pr" | "all"
    files: tuple[str, ...] = ()
    added_files: tuple[str, ...] = ()
    added_lines: dict[str, tuple[tuple[int, int], ...]] = field(default_factory=dict)
    reviewers: tuple[str, ...] | None = None
    approvals: int | None = None
    new_neurons: tuple[NewNeuron, ...] = ()


@dataclass(frozen=True)
class ReviewerSuggestion:
    """One suggested reviewer with a machine-readable role and human reason."""

    email: str
    lobe: str
    reason: str
    role: str  # "primary" | "secondary" | "backup"

    def to_dict(self) -> dict[str, str]:
        return {
            "email": self.email,
            "lobe": self.lobe,
            "reason": self.reason,
            "role": self.role,
        }


# ---------------------------------------------------------------------------
# Local git diff
# ---------------------------------------------------------------------------


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )


def _parse_patch(patch: str) -> tuple[dict[str, tuple[tuple[int, int], ...]], set[str]]:
    """Parse added line ranges and newly-added files from a unified diff."""
    added_lines: dict[str, list[tuple[int, int]]] = {}
    added_files: set[str] = set()
    current: str | None = None
    is_new_file = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current = None
            is_new_file = False
        elif line.startswith("new file mode"):
            is_new_file = True
        elif line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                current = None
            else:
                current = target.removeprefix("b/")
                if is_new_file:
                    added_files.add(current)
                    is_new_file = False
        elif current is not None and line.startswith("@@"):
            match = _HUNK_RE.match(line)
            if match is None:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            if count > 0:
                added_lines.setdefault(current, []).append((start, start + count - 1))
    return (
        {path: tuple(ranges) for path, ranges in added_lines.items()},
        added_files,
    )


def changes_from_diff(root: Path, ref: str) -> ChangeSet:
    """Read a local diff against *ref* (read-only git)."""
    status = _run_git(root, ["diff", "--name-status", ref, "--"])
    if status.returncode != 0:
        detail = status.stderr.strip() or f"git diff failed for ref '{ref}'"
        raise ValueError(detail)

    files: list[str] = []
    added_files: set[str] = set()
    for line in status.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        if code.startswith("R") and len(parts) >= 3:
            files.append(parts[2])
        else:
            files.append(parts[1])
        if code.startswith("A"):
            added_files.add(files[-1])

    patch = _run_git(root, ["diff", "-U0", "--no-color", ref, "--"])
    if patch.returncode == 0:
        patch_lines, patch_added = _parse_patch(patch.stdout)
        added_files.update(patch_added)
    else:
        patch_lines = {}

    return ChangeSet(
        source="diff",
        files=tuple(dict.fromkeys(files)),
        added_files=tuple(sorted(added_files)),
        added_lines=patch_lines,
    )


# ---------------------------------------------------------------------------
# GitHub PR mode
# ---------------------------------------------------------------------------


def _run_gh(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GH_TIMEOUT,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubNotAuthenticatedError(
            "GitHub CLI ('gh') is unavailable — install it and run 'gh auth login'."
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "gh command failed"
        raise GitHubNotAuthenticatedError(
            f"GitHub CLI is not authenticated or the PR is unavailable: {detail}. "
            "Run 'gh auth login'."
        )
    return result.stdout


def _parse_reviews(raw: str) -> tuple[tuple[str, ...], int]:
    """Return (reviewer logins, approval count) from ``gh pr view --json reviews``."""
    import json

    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return (), 0
    latest: dict[str, str] = {}
    order: list[str] = []
    reviews = payload.get("reviews") or []
    if not isinstance(reviews, list):
        return (), 0
    for review in reviews:
        if not isinstance(review, dict):
            continue
        author = review.get("author")
        login = author.get("login") if isinstance(author, dict) else None
        state = review.get("state")
        if not isinstance(login, str) or not login:
            continue
        if login not in latest:
            order.append(login)
        latest[login] = str(state or "")
    approvals = sum(1 for state in latest.values() if state == "APPROVED")
    return tuple(order), approvals


def changes_from_pr(pr: int) -> ChangeSet:
    """Read PR files and review state through the GitHub CLI (read-only)."""
    patch = _run_gh(["pr", "diff", str(pr)])
    added_lines, added_files = _parse_patch(patch)

    files: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target and target != "/dev/null":
                files.append(target.removeprefix("b/"))
        elif line.startswith("diff --git "):
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                files.append(parts[1].strip())

    metadata = _run_gh(["pr", "view", str(pr), "--json", "reviews"])
    reviewers, approvals = _parse_reviews(metadata)

    return ChangeSet(
        source="pr",
        files=tuple(dict.fromkeys(files)),
        added_files=tuple(sorted(added_files)),
        added_lines=added_lines,
        reviewers=reviewers,
        approvals=approvals,
    )


# ---------------------------------------------------------------------------
# New-neuron detection
# ---------------------------------------------------------------------------


def detect_new_neurons(conn: sqlite3.Connection, changes: ChangeSet) -> ChangeSet:
    """Return *changes* with ``new_neurons`` populated from the index."""
    if not changes.files:
        return changes

    found: dict[str, NewNeuron] = {}
    for file in changes.added_files:
        for node_id, name in conn.execute(
            "SELECT id, name FROM nodes WHERE file = ? AND type != 'module'", (file,)
        ):
            found[str(node_id)] = NewNeuron(id=str(node_id), name=str(name), file=file)

    for file, ranges in changes.added_lines.items():
        rows = conn.execute(
            "SELECT id, name, line_start, line_end FROM nodes "
            "WHERE file = ? AND type != 'module'",
            (file,),
        ).fetchall()
        for node_id, name, line_start, line_end in rows:
            start = int(line_start or 0)
            end = int(line_end or start)
            if any(start <= high and end >= low for low, high in ranges):
                found[str(node_id)] = NewNeuron(
                    id=str(node_id), name=str(name), file=file
                )

    return ChangeSet(
        source=changes.source,
        files=changes.files,
        added_files=changes.added_files,
        added_lines=changes.added_lines,
        reviewers=changes.reviewers,
        approvals=changes.approvals,
        new_neurons=tuple(found[key] for key in sorted(found)),
    )


# ---------------------------------------------------------------------------
# Reviewer suggestions
# ---------------------------------------------------------------------------


def _active_agent_emails() -> frozenset[str]:
    """Best-effort multi-agent registry lookup (Idea #25).

    The registry is not part of this codebase yet, so the integration is
    deliberately soft: any import/shape mismatch degrades to "no exclusions".
    """
    try:
        module = importlib.import_module("cerebrofy.coordination.registry")
        getter = getattr(module, "active_agent_emails", None)
        if not callable(getter):
            return frozenset()
        values = getter()
        return frozenset(str(value) for value in values)
    except Exception:  # noqa: BLE001
        return frozenset()


def _changed_lobes(changes: ChangeSet, lobes: dict[str, str]) -> list[str]:
    names = {lobe_for_file(file, lobes) for file in changes.files}
    names.discard("__unknown__")
    return sorted(names)


def suggest_reviewers(
    conn: sqlite3.Connection,
    repo_root: Path,
    lobes: dict[str, str],
    changes: ChangeSet | None = None,
    *,
    strategy: str = "git-blame",
    activity_days: int = DEFAULT_ACTIVITY_DAYS,
    team: TeamConfig | None = None,
    ownership: dict[str, LobeOwnership] | None = None,
) -> tuple[ReviewerSuggestion, ...]:
    """Suggest primary, secondary, and backup reviewers for a change set."""
    effective_team = team if team is not None else load_team_config(repo_root)
    profiles = ownership or compute_all_lobe_ownership(
        conn,
        repo_root,
        lobes,
        strategy=strategy,
        activity_days=activity_days,
        team=effective_team,
    )
    excluded = _active_agent_emails()
    selected: dict[tuple[str, str], ReviewerSuggestion] = {}

    if changes is not None and changes.files:
        targets = _changed_lobes(changes, lobes)
    else:
        targets = sorted(lobes)

    def add(email: str | None, lobe: str, role: str, reason: str) -> None:
        if not email or email in excluded:
            return
        key = (email, role)
        if key in selected:
            return
        if any(item.email == email for item in selected.values()):
            return
        selected[key] = ReviewerSuggestion(
            email=email, lobe=lobe, reason=reason, role=role
        )

    for lobe in targets:
        profile = profiles.get(lobe)
        if profile is None or profile.primary is None:
            continue
        share = f"{profile.primary_share:.0%} of blamed lines"
        add(
            profile.primary,
            lobe,
            "primary",
            f"{lobe} primary owner ({share})",
        )

    cross = cross_lobe_callers(conn, lobes)
    forward: dict[str, list[CrossLobeCall]] = {}
    for target_lobe, callers in cross.items():
        for caller in callers:
            forward.setdefault(caller.caller_lobe, []).append(
                CrossLobeCall(caller_lobe=target_lobe, count=caller.count)
            )

    for lobe in targets:
        relations: list[tuple[str, CrossLobeCall, str]] = []
        for caller in cross.get(lobe, ()):
            relations.append((caller.caller_lobe, caller, "calls into"))
        for forward_call in forward.get(lobe, ()):
            relations.append(
                (forward_call.caller_lobe, forward_call, "is called by")
            )
        for other_lobe, relation, direction in sorted(
            relations, key=lambda item: (-item[1].count, item[0])
        ):
            if other_lobe == lobe:
                continue
            profile = profiles.get(other_lobe)
            if profile is None or profile.primary is None:
                continue
            add(
                profile.primary,
                other_lobe,
                "secondary",
                (
                    f"{other_lobe} {direction} {lobe} "
                    f"({relation.count} cross-lobe call edge(s))"
                ),
            )

    for lobe in targets:
        profile = profiles.get(lobe)
        if profile is None or profile.primary is None:
            continue
        for author, commits in recent_contributors(
            conn,
            repo_root,
            lobes,
            lobe,
            activity_days=activity_days,
            limit=3,
        ):
            if author == profile.primary:
                continue
            add(
                author,
                lobe,
                "backup",
                f"recent contributor to {lobe} ({commits} commit(s) in {activity_days} days)",
            )
            break

    order = {"primary": 0, "secondary": 1, "backup": 2}
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (order.get(item.role, 9), item.lobe, item.email),
        )
    )
