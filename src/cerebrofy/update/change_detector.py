"""Change detector: git-based or hash-comparison change detection."""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # "M" | "D" | "A"


@dataclass(frozen=True)
class ChangeSet:
    changes: tuple[FileChange, ...]
    detected_via: str  # "git" | "hash_comparison" | "explicit"


def _is_git_repo(repo_root: Path) -> bool:
    """Return True if .git/ directory exists under repo_root."""
    return (repo_root / ".git").is_dir()


def _has_commits(repo_root: Path) -> bool:
    """Return True if the git repo has at least one commit."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _run_git_cmd(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git command; return (returncode, stdout). Never uses shell=True."""
    result = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout


def _parse_name_status(output: str) -> list[FileChange]:
    """Parse `git diff --name-status` / `git ls-files` output into FileChange list.

    Handles M/A/D lines (2 fields) and R lines (3 fields: old→deleted, new→added).
    """
    changes: list[FileChange] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        prefix = parts[0]
        if prefix.startswith("R") and len(parts) == 3:
            # Rename: old path deleted, new path added
            changes.append(FileChange(path=parts[1], status="D"))
            changes.append(FileChange(path=parts[2], status="A"))
        elif len(parts) >= 2:
            status_char = prefix[0]  # M, A, D, etc.
            if status_char in ("M", "A", "D"):
                changes.append(FileChange(path=parts[1], status=status_char))
        else:
            # git ls-files --others output: just a filename, no prefix
            changes.append(FileChange(path=parts[0], status="A"))
    return changes


def _detect_via_git(repo_root: Path) -> ChangeSet:
    """Detect changes using git subcommands."""
    changes: list[FileChange] = []

    if _has_commits(repo_root):
        _, out = _run_git_cmd(["git", "diff", "--name-status", "HEAD"], repo_root)
        changes.extend(_parse_name_status(out))
        _, out = _run_git_cmd(["git", "diff", "--name-status"], repo_root)
        changes.extend(_parse_name_status(out))

    _, out = _run_git_cmd(
        ["git", "ls-files", "--others", "--exclude-standard"], repo_root
    )
    changes.extend(_parse_name_status(out))

    # Deduplicate by path, keeping last status seen
    seen: dict[str, str] = {}
    for fc in changes:
        seen[fc.path] = fc.status
    deduped = tuple(FileChange(path=p, status=s) for p, s in seen.items())
    return ChangeSet(changes=deduped, detected_via="git")


def _detect_via_hash(
    repo_root: Path,
    conn: sqlite3.Connection,
    config: object,
) -> ChangeSet:
    """Detect changes by comparing file SHA-256 hashes against file_hashes table."""
    from cerebrofy.config.loader import CerebrоfyConfig
    from cerebrofy.ignore.ruleset import IgnoreRuleSet

    cfg: CerebrоfyConfig = config  # type: ignore[assignment]
    ignore_rules = IgnoreRuleSet.from_directory(repo_root)

    # Load indexed hashes
    indexed: dict[str, str] = {
        row[0]: row[1]
        for row in conn.execute("SELECT file, hash FROM file_hashes").fetchall()
    }

    # Walk current files
    current: dict[str, str] = {}
    for file_path in sorted(repo_root.rglob("*")):
        if not file_path.is_file():
            continue
        rel = str(file_path.relative_to(repo_root)).replace("\\", "/")
        if ignore_rules.matches(rel):
            continue
        if file_path.suffix.lower() not in cfg.tracked_extensions:
            continue
        current[rel] = hashlib.sha256(file_path.read_bytes()).hexdigest()

    changes: list[FileChange] = []
    for path, hash_ in current.items():
        if path not in indexed:
            changes.append(FileChange(path=path, status="A"))
        elif indexed[path] != hash_:
            changes.append(FileChange(path=path, status="M"))
    for path in indexed:
        if path not in current:
            changes.append(FileChange(path=path, status="D"))

    return ChangeSet(changes=tuple(changes), detected_via="hash_comparison")


def detect_changes(
    repo_root: Path,
    conn: sqlite3.Connection,
    config: object,
    explicit_files: list[str] | None,
) -> ChangeSet:
    """Detect changed files via explicit list, git, or hash comparison fallback."""
    from cerebrofy.ignore.ruleset import IgnoreRuleSet

    if explicit_files is not None:
        ignore_rules = IgnoreRuleSet.from_directory(repo_root)
        changes: list[FileChange] = []
        for path in explicit_files:
            p = Path(path)
            rel = str(p.relative_to(repo_root)).replace("\\", "/") if p.is_absolute() else path
            if not ignore_rules.matches(rel):
                status = "D" if not (repo_root / rel).exists() else "M"
                changes.append(FileChange(path=rel, status=status))
        return ChangeSet(changes=tuple(changes), detected_via="explicit")

    if _is_git_repo(repo_root):
        return _detect_via_git(repo_root)
    return _detect_via_hash(repo_root, conn, config)
