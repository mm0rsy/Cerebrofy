"""Architecture drift checker — evaluates arch rules against the live call graph.

Read-only over .cerebrofy/db/cerebrofy.db. RUNTIME_BOUNDARY edges are always
excluded from evaluation per Law II; lobe membership is derived from the
configured lobe paths (the nodes table has no lobe column).
"""

from __future__ import annotations

import fnmatch
import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from cerebrofy.analysis.blast_radius import caller_ids_within_depth2
from cerebrofy.arch.rules import (
    AllowedCallersCheck,
    ArchRule,
    Check,
    MaxBlastRadiusCheck,
    NoCyclesCheck,
    NoEdgeCheck,
    RulesConfig,
)
from cerebrofy.epistemic.state import EpistemicState, compute_epistemic_state
from cerebrofy.health.metrics import _lobe_for_file

UNKNOWN_LOBE = "__unknown__"
_ATTR_TIMEOUT = 10  # seconds, per-file git log call
_DIFF_TIMEOUT = 30  # seconds, git diff --name-only

_EDGE_FIX_HINT = (
    "Introduce an intermediate service layer or repository abstraction before this call."
)
_CYCLE_FIX_HINT = "Break the cycle by moving shared logic into a lower-level lobe."
_RADIUS_FIX_HINT = "Consider splitting this function into smaller components."


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Violation:
    """A single rule violation anchored to a source location."""

    rule_name: str
    severity: str  # "error" | "warning"
    kind: str  # "edge" | "cycle" | "blast_radius"
    location: str  # human-readable: "a.py::f → b.py::g" or a lobe cycle path
    file: str  # primary source file (relative to repo root)
    line: int
    detail: str
    src_name: str | None = None
    dst_name: str | None = None
    introduced_in: str | None = None  # "commit abc1234 by alice@co.com (2 hours ago)"


@dataclass(frozen=True)
class RuleResult:
    """Outcome of evaluating one rule — violations, or a configuration error."""

    rule: ArchRule
    violations: tuple[Violation, ...] = ()
    error: str | None = None  # configuration problem (rule was skipped)
    escalated_lobes: tuple[str, ...] = ()  # sprint-priority lobes (Idea #23)


@dataclass
class CheckResult:
    """Aggregated result of one arch check run."""

    rule_results: list[RuleResult] = field(default_factory=list)
    epistemic: EpistemicState | None = None  # index confidence (Idea #22), None when skipped

    @property
    def error_violations(self) -> tuple[Violation, ...]:
        return tuple(
            v for rr in self.rule_results if rr.error is None and rr.rule.severity == "error"
            for v in rr.violations
        )

    @property
    def warning_violations(self) -> tuple[Violation, ...]:
        return tuple(
            v for rr in self.rule_results if rr.error is None and rr.rule.severity == "warning"
            for v in rr.violations
        )

    @property
    def config_errors(self) -> tuple[tuple[str, str], ...]:
        """(rule name, error message) pairs for rules that could not be evaluated."""
        return tuple((rr.rule.name, rr.error) for rr in self.rule_results if rr.error is not None)

    @property
    def passing_rules(self) -> tuple[str, ...]:
        return tuple(
            rr.rule.name for rr in self.rule_results if rr.error is None and not rr.violations
        )

    @property
    def result(self) -> str:
        """PASS | WARN | FAIL — warnings never fail, config errors do not either."""
        if self.error_violations:
            return "FAIL"
        if self.warning_violations:
            return "WARN"
        return "PASS"


def fix_hint(kind: str, description: str) -> str:
    """Fix suggestion for a violation — rule description first, kind fallback later."""
    if description:
        return description
    hints = {
        "edge": _EDGE_FIX_HINT,
        "cycle": _CYCLE_FIX_HINT,
        "blast_radius": _RADIUS_FIX_HINT,
    }
    return hints.get(kind, "Review this usage against the rule that flagged it.")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Node:
    name: str
    file: str
    type: str
    line_start: int


@dataclass
class _Graph:
    """Snapshot of nodes + call/import edges (RUNTIME_BOUNDARY excluded)."""

    nodes: dict[str, _Node]
    edges: tuple[tuple[str, str], ...]
    in_adj: dict[str, tuple[str, ...]]


def run_arch_check(
    rules: RulesConfig,
    conn: sqlite3.Connection,
    lobes: dict[str, str],
    repo_root: Path | None = None,
    rule_name: str | None = None,
    changed_files: frozenset[str] | None = None,
    tracked_extensions: list[str] | None = None,
    priority_lobes: frozenset[str] = frozenset(),
) -> CheckResult:
    """Evaluate every rule (or a single rule when rule_name is given) against the graph.

    changed_files restricts reported violations to files in the set (the --since
    filter); None means check everything. repo_root enables best-effort
    "Introduced in" git attribution on violating edges.

    tracked_extensions (with repo_root) attaches the epistemic confidence state
    (Idea #22) so stale-graph caveats travel with the result. priority_lobes
    escalates warning-severity rules that reference a sprint-priority lobe to
    error severity for this run (Idea #23).
    """
    graph = _load_graph(conn)
    node_lobe = {nid: _lobe_for_file(info.file, lobes) for nid, info in graph.nodes.items()}

    selected = [rule for rule in rules.rules if rule_name is None or rule.name == rule_name]
    if rule_name is not None and not selected:
        raise ValueError(f"Rule '{rule_name}' not found in arch-rules.yaml")

    result = CheckResult()
    for rule in selected:
        result.rule_results.append(
            _evaluate_rule(
                rule, graph, node_lobe, lobes, repo_root, changed_files, priority_lobes
            )
        )
    if tracked_extensions is not None and repo_root is not None:
        try:
            result.epistemic = compute_epistemic_state(conn, tracked_extensions, repo_root)
        except Exception:  # enrichment only — never fail the check on it
            result.epistemic = None
    return result


def _evaluate_rule(
    rule: ArchRule,
    graph: _Graph,
    node_lobe: dict[str, str],
    lobes: dict[str, str],
    repo_root: Path | None,
    changed_files: frozenset[str] | None,
    priority_lobes: frozenset[str] = frozenset(),
) -> RuleResult:
    unknown = sorted(
        reference for reference in lobe_references(rule.check) if reference not in lobes
    )
    if unknown:
        return RuleResult(
            rule=rule,
            error=(
                f"unknown lobe(s) {', '.join(unknown)} — "
                "not present in .cerebrofy/config.yaml; rule skipped"
            ),
        )

    escalated = escalated_priority_lobes(rule, priority_lobes)
    effective_rule = replace(rule, severity="error") if escalated else rule

    attr_cache: dict[str, str | None] = {}
    error: str | None = None
    violations: list[Violation] = []
    try:
        violations = _check_rule(effective_rule, graph, node_lobe, repo_root, attr_cache)
    except Exception as exc:  # a broken rule must not crash a full check run
        error = f"rule evaluation failed: {exc}"
    if changed_files is not None and not error:
        violations = [v for v in violations if v.file in changed_files]
    return RuleResult(
        rule=effective_rule,
        violations=tuple(sorted(violations, key=_violation_sort_key)),
        error=error,
        escalated_lobes=escalated,
    )


def _check_rule(
    rule: ArchRule,
    graph: _Graph,
    node_lobe: dict[str, str],
    repo_root: Path | None,
    attr_cache: dict[str, str | None],
) -> list[Violation]:
    check = rule.check
    if isinstance(check, NoEdgeCheck):
        return _check_no_edge(rule, check, graph, node_lobe, repo_root, attr_cache)
    if isinstance(check, NoCyclesCheck):
        return _check_no_cycles(rule, graph, node_lobe)
    if isinstance(check, AllowedCallersCheck):
        return _check_allowed_callers(rule, check, graph, node_lobe, repo_root, attr_cache)
    assert isinstance(check, MaxBlastRadiusCheck)  # narrowed by the rules loader
    return _check_max_blast_radius(rule, check, graph)


def lobe_references(check: Check) -> set[str]:
    """Lobe names a check consults — used to detect misconfigured rules."""
    if isinstance(check, NoEdgeCheck):
        return {lobe for lobe in (check.from_lobe, check.to_lobe) if lobe is not None}
    if isinstance(check, AllowedCallersCheck):
        return set(check.from_lobes)
    return set()


def escalated_priority_lobes(
    rule: ArchRule,
    priority_lobes: frozenset[str] | set[str],
) -> tuple[str, ...]:
    """Sprint-priority lobes this warning rule references (Idea #23 escalation).

    Error-severity rules are already blocking, so escalation only applies to
    warnings; returns the sorted lobe-name overlap, empty when none.
    """
    if rule.severity != "warning" or not priority_lobes:
        return ()
    return tuple(sorted(lobe_references(rule.check) & set(priority_lobes)))


def _violation_sort_key(v: Violation) -> tuple[str, int, str, str]:
    return (v.file, v.line, v.src_name or "", v.dst_name or "")


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def _load_graph(conn: sqlite3.Connection) -> _Graph:
    nodes: dict[str, _Node] = {}
    for row in conn.execute("SELECT id, name, file, type, line_start FROM nodes"):
        nodes[str(row[0])] = _Node(
            name=str(row[1]), file=str(row[2]), type=str(row[3] or ""), line_start=int(row[4] or 0)
        )

    kept: list[tuple[str, str]] = []
    in_adj: dict[str, set[str]] = defaultdict(set)
    for src, dst in conn.execute(
        "SELECT src_id, dst_id FROM edges WHERE rel_type != 'RUNTIME_BOUNDARY'"
    ):
        if src not in nodes or dst not in nodes:
            continue  # external::* endpoints and dangling ids cannot be attributed
        kept.append((src, dst))
        in_adj[dst].add(src)

    edges = tuple(sorted(kept))
    adjacency = {dst: tuple(sorted(srcs)) for dst, srcs in in_adj.items()}
    return _Graph(nodes=nodes, edges=edges, in_adj=adjacency)


# ---------------------------------------------------------------------------
# Rule checks
# ---------------------------------------------------------------------------

def _check_no_edge(
    rule: ArchRule,
    check: NoEdgeCheck,
    graph: _Graph,
    node_lobe: dict[str, str],
    repo_root: Path | None,
    attr_cache: dict[str, str | None],
) -> list[Violation]:
    violations: list[Violation] = []
    for src_id, dst_id in graph.edges:
        src = graph.nodes[src_id]
        dst = graph.nodes[dst_id]
        if check.from_lobe is not None and node_lobe.get(src_id) != check.from_lobe:
            continue
        if check.from_patterns and not _matches_any(src.file, check.from_patterns):
            continue
        if check.to_lobe is not None and node_lobe.get(dst_id) != check.to_lobe:
            continue
        if check.to_patterns and not _matches_any(dst.file, check.to_patterns):
            continue
        violations.append(
            _edge_violation(rule, check, src_id, dst_id, src, dst, node_lobe, repo_root, attr_cache)
        )
    return violations


def _edge_violation(
    rule: ArchRule,
    check: NoEdgeCheck,
    src_id: str,
    dst_id: str,
    src: _Node,
    dst: _Node,
    node_lobe: dict[str, str],
    repo_root: Path | None,
    attr_cache: dict[str, str | None],
) -> Violation:
    src_side = check.from_lobe or "|".join(check.from_patterns)
    dst_side = check.to_lobe or "|".join(check.to_patterns)
    src_lobe = node_lobe.get(src_id, UNKNOWN_LOBE)
    dst_lobe = node_lobe.get(dst_id, UNKNOWN_LOBE)
    detail = (
        f"{src_side} ({src_lobe}) → {dst_side} ({dst_lobe})"
        if src_side != src_lobe or dst_side != dst_lobe
        else f"{src_lobe} → {dst_lobe}"
    )
    return Violation(
        rule_name=rule.name,
        severity=rule.severity,
        kind="edge",
        location=f"{src.file}::{src.name} → {dst.file}::{dst.name}",
        file=src.file,
        line=src.line_start,
        detail=detail,
        src_name=src.name,
        dst_name=dst.name,
        introduced_in=_introduced_in(repo_root, src.file, attr_cache),
    )


def _check_no_cycles(
    rule: ArchRule,
    graph: _Graph,
    node_lobe: dict[str, str],
) -> list[Violation]:
    lobe_edges: dict[tuple[str, str], tuple[str, int]] = {}
    children: dict[str, set[str]] = defaultdict(set)
    for src_id, dst_id in graph.edges:
        src_lobe = node_lobe.get(src_id, UNKNOWN_LOBE)
        dst_lobe = node_lobe.get(dst_id, UNKNOWN_LOBE)
        if src_lobe == UNKNOWN_LOBE or dst_lobe == UNKNOWN_LOBE or src_lobe == dst_lobe:
            continue
        edge = (src_lobe, dst_lobe)
        if edge not in lobe_edges:
            lobe_edges[edge] = (graph.nodes[src_id].file, graph.nodes[src_id].line_start)
        children[src_lobe].add(dst_lobe)

    cycles = _find_lobe_cycles(children)
    violations: list[Violation] = []
    seen: set[frozenset[str]] = set()
    for cycle in cycles:
        key = frozenset(cycle[:-1])
        if key in seen:
            continue
        seen.add(key)
        closing_file, closing_line = lobe_edges.get((cycle[-2], cycle[-1]), ("", 0))
        violations.append(
            Violation(
                rule_name=rule.name,
                severity=rule.severity,
                kind="cycle",
                location=" → ".join(cycle),
                file=closing_file,
                line=closing_line,
                detail=f"circular dependency through {len(cycle) - 1} lobes",
                src_name=cycle[-2],
                dst_name=cycle[-1],
            )
        )
    return violations


def _find_lobe_cycles(children: dict[str, set[str]]) -> list[list[str]]:
    """Depth-first cycle detection over the lobe graph, one cycle per back edge."""
    white, gray, black = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    path: list[str] = []
    cycles: list[list[str]] = []

    def visit(lobe: str) -> None:
        color[lobe] = gray
        path.append(lobe)
        for nxt in sorted(children.get(lobe, ())):
            if color[nxt] == gray:
                start = path.index(nxt)
                cycles.append(path[start:] + [nxt])
            elif color[nxt] == white:
                visit(nxt)
        color[lobe] = black
        path.pop()

    for lobe in sorted(children):
        if color[lobe] == white:
            visit(lobe)
    return cycles


def _check_allowed_callers(
    rule: ArchRule,
    check: AllowedCallersCheck,
    graph: _Graph,
    node_lobe: dict[str, str],
    repo_root: Path | None,
    attr_cache: dict[str, str | None],
) -> list[Violation]:
    targets = {nid for nid, node in graph.nodes.items() if _match_neuron(node, check.neuron)}
    if not targets:
        return []  # pattern matches no neurons — nothing to enforce yet
    violations: list[Violation] = []
    for src_id, dst_id in graph.edges:
        if dst_id not in targets:
            continue
        src = graph.nodes[src_id]
        dst = graph.nodes[dst_id]
        src_lobe = node_lobe.get(src_id, UNKNOWN_LOBE)
        if src_lobe in check.from_lobes:
            continue
        violations.append(
            Violation(
                rule_name=rule.name,
                severity=rule.severity,
                kind="edge",
                location=f"{src.file}::{src.name} → {dst.file}::{dst.name}",
                file=src.file,
                line=src.line_start,
                detail=f"caller lobe '{src_lobe}' is not in allowed {', '.join(check.from_lobes)}",
                src_name=src.name,
                dst_name=dst.name,
                introduced_in=_introduced_in(repo_root, src.file, attr_cache),
            )
        )
    return violations


def _check_max_blast_radius(
    rule: ArchRule,
    check: MaxBlastRadiusCheck,
    graph: _Graph,
) -> list[Violation]:
    violations: list[Violation] = []
    for nid, node in graph.nodes.items():
        if node.type == "module":
            continue
        # Shared metric with the blast-radius analyzer (Idea #01): the same
        # depth-1 + depth-2 caller-set semantics as bfs_callers().
        radius = len(caller_ids_within_depth2(nid, graph.in_adj))
        if radius <= check.limit:
            continue
        violations.append(
            Violation(
                rule_name=rule.name,
                severity=rule.severity,
                kind="blast_radius",
                location=f"{node.file}::{node.name}",
                file=node.file,
                line=node.line_start,
                detail=f"blast_radius={radius} (limit: {check.limit})",
                src_name=node.name,
                dst_name=None,
            )
        )
    return violations


def _match_neuron(node: _Node, pattern: str) -> bool:
    return bool(
        fnmatch.fnmatchcase(f"{node.file}::{node.name}", pattern)
        or fnmatch.fnmatchcase(node.name, pattern)
        or fnmatch.fnmatchcase(node.file, pattern)
    )


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(text, pattern) for pattern in patterns)


# ---------------------------------------------------------------------------
# Git helpers (best-effort attribution)
# ---------------------------------------------------------------------------

def changed_files_since(root: Path, ref: str) -> tuple[str, ...]:
    """Files changed between `ref` and the working tree (committed + uncommitted)."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", ref],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=_DIFF_TIMEOUT,
    )
    if proc.returncode != 0:
        raise ValueError(f"git could not diff against ref '{ref}': {proc.stderr.strip()}")
    return tuple(line for line in proc.stdout.splitlines() if line.strip())


def _introduced_in(root: Path | None, file: str, cache: dict[str, str | None]) -> str | None:
    """Best-effort "commit abc1234 by author (2 hours ago)" via git log -1 on file."""
    if root is None or not (root / ".git").exists():
        return None
    if file in cache:
        return cache[file]
    cache[file] = _git_last_commit(root, file)
    return cache[file]


def _git_last_commit(root: Path, file: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%h|%ae|%ar", "--", file],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_ATTR_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    parts = proc.stdout.strip().split("|", 2)
    if len(parts) != 3:
        return None
    commit, author, when = (part.strip() for part in parts)
    if not commit or commit.startswith("%"):
        return None
    return f"commit {commit} by {author} ({when})"
