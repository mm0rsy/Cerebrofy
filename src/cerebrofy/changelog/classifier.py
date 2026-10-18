"""Changelog classifier: changed neurons → semantic entry types.

Classification is derived from the semantic graph — drift records (#16),
blast radius (#01), agent memories (#05), vulnerability/security tags (#08),
and product intent (#23) — never from commit messages.
"""

from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cerebrofy.analysis.blast_radius import bfs_callers
from cerebrofy.memory.store import Memory
from cerebrofy.update.change_detector import detect_changes_between_refs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: All entry types a changelog entry can carry.
ENTRY_TYPES: tuple[str, ...] = (
    "feat",
    "fix",
    "refactor",
    "security",
    "breaking",
    "perf",
    "internal",
    "intent_update",
)

FEAT = "feat"
FIX = "fix"
REFACTOR = "refactor"
SECURITY = "security"
BREAKING = "breaking"
PERF = "perf"
INTERNAL = "internal"
INTENT_UPDATE = "intent_update"

#: Change kinds at the neuron level.
KIND_ADDED = "added"
KIND_MODIFIED = "modified"
KIND_SIGNATURE_CHANGED = "signature_changed"
KIND_REMOVED = "removed"
KIND_MOVED = "moved"

#: More than this many cross-lobe direct callers ⇒ breaking (spec).
BREAKING_CROSS_LOBE_CALLERS = 3

#: Error codes surfaced to the CLI and MCP tool (spec §Error Codes).
CODE_NO_INDEX = "NO_INDEX"
CODE_REF_NOT_FOUND = "REF_NOT_FOUND"

_SECURITY_TAGS = frozenset({"security", "vuln", "cve", "vulnerability"})
_PERF_TAGS = frozenset({"perf", "performance"})

_REV_PARSE_TIMEOUT = 15  # seconds


class ChangelogError(Exception):
    """Changelog failure carrying a spec error code (NO_INDEX / REF_NOT_FOUND)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedRange:
    """A user-supplied `--since` value resolved to concrete git refs."""

    since_label: str  # what the user typed (tag, hash, last-build, project-start)
    since_ref: str  # resolved commit hash for diffing
    until_ref: str  # resolved HEAD commit hash
    note: str | None = None  # non-fatal resolution note (e.g. last-build fallback)


@dataclass(frozen=True)
class NeuronChange:
    """A single changed neuron within a git range."""

    id: str  # "file::name"
    name: str
    file: str
    lobe: str
    kind: str  # KIND_ADDED | KIND_MODIFIED | KIND_SIGNATURE_CHANGED | KIND_REMOVED


@dataclass(frozen=True)
class CollectedChanges:
    """Result of collecting change evidence for a git range."""

    range: ResolvedRange
    changes: tuple[NeuronChange, ...]
    files: tuple[str, ...]  # changed file paths between the refs


@dataclass(frozen=True)
class ClassifiedChange:
    """One or more NeuronChanges sharing a single semantic entry type."""

    entry_type: str
    neurons: tuple[NeuronChange, ...]
    direct_callers: int
    cross_lobe_callers: int
    blast_radius: int
    is_breaking: bool
    public_surface: bool
    memories: tuple[Memory, ...]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str], repo_root: Path) -> str | None:
    """Run a git command; return stdout on success, None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_REV_PARSE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _rev_parse(ref: str, repo_root: Path) -> str | None:
    out = _run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], repo_root)
    return out or None


def is_test_file(file: str) -> bool:
    """True when *file* lives under tests/ or is named like a test module."""
    parts = Path(file).parts
    if parts and parts[0] == "tests":
        return True
    name = Path(file).name
    return name.startswith("test_") or name.endswith("_test.py")


def lobe_for_file(file: str, lobes: Mapping[str, str] | None = None) -> str:
    """Map a file path to its lobe name.

    Uses the configured lobe paths when provided; otherwise falls back to the
    first path segment (mirroring the blast radius engine's convention).
    """
    if lobes:
        for name, path in lobes.items():
            norm = path.rstrip("/")
            if norm and norm != "." and (file == norm or file.startswith(norm + "/")):
                return name
    parts = Path(file).parts
    return parts[0] if len(parts) > 1 else file


# ---------------------------------------------------------------------------
# Range resolution
# ---------------------------------------------------------------------------


def _last_build_commit(conn: sqlite3.Connection) -> str | None:
    """Commit hash recorded by the most recent health snapshot, if any."""
    try:
        row = conn.execute(
            "SELECT commit_hash FROM health_snapshots ORDER BY build_ts DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row and row[0] else None


def resolve_range(
    repo_root: Path,
    since: str,
    conn: sqlite3.Connection,
) -> ResolvedRange:
    """Resolve a user-supplied --since value to commit hashes.

    Accepts a git tag, a commit hash, ``last-build`` (the commit recorded by
    the newest health snapshot), or ``project-start`` (root commit).

    Raises:
        ChangelogError(REF_NOT_FOUND): the ref cannot be resolved.
    """
    until_ref = _rev_parse("HEAD", repo_root)
    if until_ref is None:
        raise ChangelogError(
            CODE_REF_NOT_FOUND, "Could not resolve HEAD — is this a git repository with commits?"
        )

    if since == "project-start":
        roots = _run_git(["rev-list", "--max-parents=0", until_ref], repo_root)
        if not roots:
            raise ChangelogError(CODE_REF_NOT_FOUND, "Could not find the project's root commit.")
        return ResolvedRange(since_label=since, since_ref=roots.splitlines()[-1], until_ref=until_ref)

    if since == "last-build":
        commit = _last_build_commit(conn)
        if commit is None:
            note = (
                "no build commit recorded (health snapshot missing) — "
                "reporting no changes since HEAD"
            )
            return ResolvedRange(
                since_label=since, since_ref=until_ref, until_ref=until_ref, note=note
            )
        resolved = _rev_parse(commit, repo_root)
        if resolved is None:
            note = f"last-build commit '{commit}' is not in this repository — falling back to HEAD"
            return ResolvedRange(
                since_label=since, since_ref=until_ref, until_ref=until_ref, note=note
            )
        return ResolvedRange(since_label=since, since_ref=resolved, until_ref=until_ref)

    resolved = _rev_parse(since, repo_root)
    if resolved is None:
        raise ChangelogError(
            CODE_REF_NOT_FOUND,
            f"Git ref '{since}' not found. Use a tag, a commit hash, "
            "'last-build', or 'project-start'.",
        )
    return ResolvedRange(since_label=since, since_ref=resolved, until_ref=until_ref)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _indexed_neurons(
    conn: sqlite3.Connection, file: str
) -> list[tuple[str, str]]:
    """(name, type) of every indexed neuron in *file*."""
    rows = conn.execute(
        "SELECT name, type FROM nodes WHERE file = ?", (file,)
    ).fetchall()
    return [(row[0], row[1] or "") for row in rows]


def collect_changes(
    repo_root: Path,
    conn: sqlite3.Connection,
    since: str,
    config: object = None,
    resolved: ResolvedRange | None = None,
) -> CollectedChanges:
    """Collect per-neuron changes for the range *since*..HEAD.

    Structural detail comes from the drift classifier (#16) when the working
    tree differs from the index. When the index is already up to date, git's
    file status (A/M/D) is used as the durable signal and every non-module
    neuron in a changed file becomes a candidate change.

    Raises:
        ChangelogError(REF_NOT_FOUND): the range cannot be resolved.
    """
    from cerebrofy.validate.drift_classifier import classify_drift

    range_ = resolved or resolve_range(repo_root, since, conn)
    cfg_lobes: Mapping[str, str] | None = None
    if config is not None:
        cfg_lobes = getattr(config, "lobes", None) or None

    changeset = detect_changes_between_refs(repo_root, range_.since_ref, range_.until_ref)
    file_status: dict[str, str] = {}
    for fc in changeset.changes:
        file_status[fc.path] = fc.status  # last status wins (renames → add)

    changed_files = tuple(sorted(file_status))
    drift_by_file: dict[str, Any] = {}
    if changed_files:
        records = classify_drift(list(changed_files), conn, config, repo_root)
        drift_by_file = {r.file: r for r in records}

    changes: list[NeuronChange] = []
    for file in changed_files:
        status = file_status[file]
        lobe = lobe_for_file(file, cfg_lobes)

        if status == "D":
            for name, ntype in _indexed_neurons(conn, file):
                if ntype == "module":
                    continue
                changes.append(
                    NeuronChange(
                        id=f"{file}::{name}", name=name, file=file, lobe=lobe, kind=KIND_REMOVED
                    )
                )
            continue

        record = drift_by_file.get(file)
        if record is not None and record.neuron_details:
            for detail in record.neuron_details:
                if detail.neuron_type == "module":
                    continue
                changes.append(
                    NeuronChange(
                        id=f"{file}::{detail.name}",
                        name=detail.name,
                        file=file,
                        lobe=lobe,
                        kind=detail.kind,
                    )
                )
            continue

        # Index already matches the working tree (or only non-structural edits):
        # fall back to git status + the indexed neuron list for the file.
        kind = KIND_ADDED if status == "A" else KIND_MODIFIED
        for name, ntype in _indexed_neurons(conn, file):
            if ntype == "module":
                continue
            changes.append(
                NeuronChange(id=f"{file}::{name}", name=name, file=file, lobe=lobe, kind=kind)
            )

    return CollectedChanges(
        range=range_, changes=tuple(changes), files=changed_files
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _has_tag(memories: Sequence[Memory], tags: frozenset[str]) -> bool:
    return any(tags.intersection(t.lower() for t in m.tags) for m in memories)


def _mentions_cve(memories: Sequence[Memory]) -> bool:
    return any(
        "cve" in m.title.lower() or "cve" in m.body.lower() for m in memories
    )


def _has_warning(memories: Sequence[Memory]) -> bool:
    return any(m.type == "warning" for m in memories)


def _caller_stats(
    neuron_id: str,
    neuron_lobe: str,
    conn: sqlite3.Connection,
    lobes: Mapping[str, str] | None,
) -> tuple[int, int, int]:
    """(direct_callers, cross_lobe_callers, blast_radius) excluding test files."""
    depth1, depth2, _runtime = bfs_callers(neuron_id, conn, max_depth=2)

    direct = 0
    cross = 0
    for caller in depth1:
        if is_test_file(caller.file):
            continue
        direct += 1
        if lobe_for_file(caller.file, lobes) != neuron_lobe:
            cross += 1

    blast = direct + sum(1 for n in depth2 if not is_test_file(n.file))
    return direct, cross, blast


def is_breaking_change(
    kind: str,
    direct_callers: int,
    cross_lobe_callers: int,
) -> bool:
    """Breaking-change heuristics (recall-first per spec acceptance criteria).

    * removed neuron that still has callers in the index;
    * signature change on a public surface (≥1 caller in another lobe);
    * any change with more than :data:`BREAKING_CROSS_LOBE_CALLERS` cross-lobe callers.
    """
    if kind == KIND_ADDED or kind == KIND_MOVED:
        return False
    if kind == KIND_REMOVED:
        return direct_callers >= 1
    if cross_lobe_callers > BREAKING_CROSS_LOBE_CALLERS:
        return True
    if kind == KIND_SIGNATURE_CHANGED and cross_lobe_callers >= 1:
        return True
    return False


def classify_change(
    change: NeuronChange,
    conn: sqlite3.Connection,
    memories: Sequence[Memory] = (),
    lobes: Mapping[str, str] | None = None,
) -> ClassifiedChange:
    """Classify a single changed neuron into a changelog entry type.

    Precedence (breaking-first so breaking changes are never missed):

    ``added → breaking → security → perf → fix → internal``

    (``refactor`` for neurons moved across lobes, see :func:`classify_changes`.)
    """
    direct, cross, blast = _caller_stats(change.id, change.lobe, conn, lobes)
    breaking = is_breaking_change(change.kind, direct, cross)

    if change.kind == KIND_ADDED:
        entry_type = FEAT
    elif breaking:
        entry_type = BREAKING
    elif _has_tag(memories, _SECURITY_TAGS) or _mentions_cve(memories):
        entry_type = SECURITY
    elif _has_tag(memories, _PERF_TAGS):
        entry_type = PERF
    elif change.kind in (KIND_SIGNATURE_CHANGED, KIND_MODIFIED) and _has_warning(memories):
        entry_type = FIX
    else:
        entry_type = INTERNAL

    return ClassifiedChange(
        entry_type=entry_type,
        neurons=(change,),
        direct_callers=direct,
        cross_lobe_callers=cross,
        blast_radius=blast,
        is_breaking=breaking,
        public_surface=cross >= 1 and not is_test_file(change.file),
        memories=tuple(memories),
    )


def classify_changes(
    changes: Sequence[NeuronChange],
    conn: sqlite3.Connection,
    memories_by_neuron: Mapping[str, Sequence[Memory]] | None = None,
    lobes: Mapping[str, str] | None = None,
) -> list[ClassifiedChange]:
    """Classify all changes; merge cross-lobe moves into single refactor entries."""
    memories_by_neuron = memories_by_neuron or {}

    added_by_name = {c.name: c for c in changes if c.kind == KIND_ADDED}
    consumed: set[str] = set()
    results: list[ClassifiedChange] = []

    # Detect moves: same name removed from one lobe, added in another.
    for removed in [c for c in changes if c.kind == KIND_REMOVED]:
        added = added_by_name.get(removed.name)
        if added is None or added.lobe == removed.lobe:
            continue
        consumed.add(removed.id)
        consumed.add(added.id)
        merged = NeuronChange(
            id=removed.id,
            name=removed.name,
            file=removed.file,
            lobe=added.lobe,
            kind=KIND_MOVED,
        )
        direct, cross, blast = _caller_stats(merged.id, removed.lobe, conn, lobes)
        mems = tuple(memories_by_neuron.get(removed.id, ()))
        results.append(
            ClassifiedChange(
                entry_type=REFACTOR,
                neurons=(merged, added),
                direct_callers=direct,
                cross_lobe_callers=cross,
                blast_radius=blast,
                is_breaking=False,
                public_surface=False,
                memories=mems,
            )
        )

    for change in changes:
        if change.id in consumed:
            continue
        mems = tuple(memories_by_neuron.get(change.id, ()))
        results.append(classify_change(change, conn, mems, lobes))

    return results
