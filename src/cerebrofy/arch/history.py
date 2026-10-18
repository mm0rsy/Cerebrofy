"""Append-only JSONL history of architecture check runs (.cerebrofy/arch-history.jsonl)."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cerebrofy.arch.checker import CheckResult

HISTORY_FILENAME = "arch-history.jsonl"
MAX_ENTRIES = 2000


@dataclass(frozen=True)
class RuleFailure:
    """One rule's failure in a single archived run."""

    rule: str
    severity: str
    count: int


@dataclass(frozen=True)
class HistoryEntry:
    """One archived arch check run."""

    ts: int
    result: str  # PASS | WARN | FAIL
    rules_checked: int
    commit: str | None = None
    since: str | None = None
    passing: tuple[str, ...] = ()
    failing: tuple[RuleFailure, ...] = ()
    config_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ts": self.ts,
            "result": self.result,
            "rules_checked": self.rules_checked,
        }
        if self.commit is not None:
            d["commit"] = self.commit
        if self.since is not None:
            d["since"] = self.since
        d["passing"] = list(self.passing)
        d["failing"] = [
            {"rule": f.rule, "severity": f.severity, "count": f.count} for f in self.failing
        ]
        d["config_errors"] = list(self.config_errors)
        return d


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def history_path(root: Path) -> Path:
    """Return .cerebrofy/arch-history.jsonl under repo root."""
    return root / ".cerebrofy" / HISTORY_FILENAME


def entry_from_result(
    result: CheckResult, commit: str | None, since: str | None
) -> HistoryEntry:
    """Snapshot a finished CheckResult into a history entry (names/counts only)."""
    failing = tuple(
        RuleFailure(rr.rule.name, rr.rule.severity, len(rr.violations))
        for rr in result.rule_results
        if rr.error is None and rr.violations
    )
    config_errors = tuple(
        f"'{rr.rule.name}': {rr.error}" for rr in result.rule_results if rr.error is not None
    )
    return HistoryEntry(
        ts=int(time.time()),        result=result.result,
        rules_checked=len(result.rule_results),
        commit=commit,
        since=since,
        passing=result.passing_rules,
        failing=failing,
        config_errors=config_errors,
    )


def record_history(root: Path, entry: HistoryEntry, max_entries: int = MAX_ENTRIES) -> None:
    """Append an entry, trimming the oldest rows once max_entries is exceeded."""
    path = history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(_encode(entry), sort_keys=True)
    if not path.exists():
        path.write_text(line + "\n", encoding="utf-8")
        return
    existing = path.read_text(encoding="utf-8").splitlines()
    rows = [row for row in existing if row.strip()]
    rows.append(line)
    if len(rows) > max_entries:
        rows = rows[-max_entries:]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    else:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _encode(entry: HistoryEntry) -> dict[str, Any]:
    return entry.to_dict()


def read_history(root: Path) -> list[HistoryEntry]:
    """Return entries oldest → newest. Malformed lines are skipped."""
    path = history_path(root)
    if not path.exists():
        return []
    entries: list[HistoryEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = _decode_line(line)
        if entry is not None:
            entries.append(entry)
    return entries


def _decode_line(line: str) -> HistoryEntry | None:
    try:
        data = json.loads(line)
        failing = tuple(
            RuleFailure(
                rule=str(item.get("rule", "")),
                severity=str(item.get("severity", "")),
                count=int(item.get("count", 0)),
            )
            for item in data.get("failing", [])
            if isinstance(item, dict)
        )
        return HistoryEntry(
            ts=int(data.get("ts", 0)),
            result=str(data.get("result", "")),
            rules_checked=int(data.get("rules_checked", 0)),
            commit=data.get("commit"),
            since=data.get("since"),
            passing=tuple(str(p) for p in data.get("passing", [])),
            failing=failing,
            config_errors=tuple(str(e) for e in data.get("config_errors", [])),
        )
    except (ValueError, TypeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------

def first_violation_map(entries: list[HistoryEntry]) -> dict[str, HistoryEntry]:
    """Rule name → earliest entry (chronological scan) in which it was violated."""
    first: dict[str, HistoryEntry] = {}
    for entry in entries:
        for failure in entry.failing:
            if failure.count > 0 and failure.rule not in first:
                first[failure.rule] = entry
    return first


@dataclass(frozen=True)
class HistorySummary:
    """Aggregated trend view over recent arch check runs (for cerebrofy health)."""

    runs: int                  # runs considered (the summary window)
    latest_result: str | None  # PASS | WARN | FAIL of the newest run
    latest_ts: int | None
    latest_commit: str | None
    error_count: int           # error-severity violations in the newest run
    warning_count: int         # warning-severity violations in the newest run
    series: tuple[int, ...]    # total violations per run, oldest → newest


def summarize_history(entries: list[HistoryEntry], limit: int = 10) -> HistorySummary:
    """Summarize the newest *limit* runs: latest counts + per-run violation totals.

    Idea #03 integration: the total-violation series is the health metric that
    cerebrofy health trends over time.
    """
    recent = entries[-limit:] if limit > 0 else []
    if not recent:
        return HistorySummary(0, None, None, None, 0, 0, ())
    latest = recent[-1]
    return HistorySummary(
        runs=len(recent),
        latest_result=latest.result,
        latest_ts=latest.ts,
        latest_commit=latest.commit,
        error_count=sum(f.count for f in latest.failing if f.severity == "error"),
        warning_count=sum(f.count for f in latest.failing if f.severity != "error"),
        series=tuple(sum(f.count for f in entry.failing) for entry in recent),
    )


def current_commit(root: Path) -> str | None:
    """Best-effort short HEAD hash; None outside git repos or before first commit."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    commit = proc.stdout.strip()
    return commit or None
