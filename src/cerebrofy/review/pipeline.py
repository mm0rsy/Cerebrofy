"""Review pipeline — orchestrate graph-aware checks for a diff or pull request.

Every check is a thin adapter over an existing analysis module:

* blast radius        -> :mod:`cerebrofy.analysis.blast_radius`
* memory warnings     -> :mod:`cerebrofy.memory.store`
* architecture rules  -> :mod:`cerebrofy.arch.checker`
* coverage gaps       -> :mod:`cerebrofy.analysis.coverage_gap`
* coupling / health   -> :mod:`cerebrofy.health.metrics` semantics
* knowledge silos     -> :mod:`cerebrofy.analysis.silo_detector`

Optional integrations degrade gracefully: a missing ``memories.db``, absent
``arch-rules.yaml``, missing git history, or no ``coverage.xml`` adds a note to
``ReviewReport.skipped_checks`` (where appropriate) and never aborts the review.
"""

from __future__ import annotations

import datetime
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from cerebrofy.analysis.blast_radius import (
    BlastNeuron,
    NeuronBlastRadius,
    compute_neuron_blast_radius,
    neurons_for_changed_files,
)
from cerebrofy.analysis.coverage_gap import _detect_covered_neurons
from cerebrofy.analysis.silo_detector import _authors_for_range, _blame_file
from cerebrofy.arch.checker import fix_hint, run_arch_check
from cerebrofy.arch.rules import RulesError
from cerebrofy.config.loader import load_arch_rules, load_config
from cerebrofy.db.connection import check_schema_version
from cerebrofy.epistemic.state import compute_epistemic_state
from cerebrofy.errors import (
    CEREBROFY_ERROR,
    GH_NOT_AUTHENTICATED,
    NO_DIFF_PROVIDED,
    NO_INDEX,
    REF_NOT_FOUND,
    CerebrofyError,
)
from cerebrofy.intent.loader import sprint_priority_lobes
from cerebrofy.memory.store import Memory, list_memories
from cerebrofy.review.finding import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Finding,
    HealthDelta,
    ReviewReport,
    SuggestedReviewer,
    compute_severity_score,
    filter_findings,
    format_summary,
    sort_findings,
)

_GIT_TIMEOUT = 30
_GH_TIMEOUT = 30
_MEMORY_BODY_LIMIT = 500


class ReviewError(CerebrofyError):
    """A review could not run because an input or prerequisite is missing."""

    code: str = CEREBROFY_ERROR


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def normalize_changed_files(paths: list[str]) -> list[str]:
    """Normalise, de-duplicate, and preserve the order of changed paths."""
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = raw.strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def resolve_changed_files(
    *,
    diff: str | None = None,
    pr: int | None = None,
    repo_root: Path,
) -> list[str]:
    """Resolve changed files from a git ref or a GitHub pull request.

    ``diff`` uses ``git diff --name-only <ref>`` (read-only, supports
    ``HEAD`` for uncommitted changes).  ``pr`` uses ``gh pr diff --name-only``
    and therefore requires an authenticated ``gh`` CLI.  No network access
    happens for the local diff mode.
    """
    if pr is not None:
        command = ["gh", "pr", "diff", str(pr), "--name-only"]
        try:
            completed = subprocess.run(
                command,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise ReviewError(
                "gh CLI is not installed or not authenticated. "
                "Install gh and run 'gh auth login'.",
                code=GH_NOT_AUTHENTICATED,
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "gh pr diff failed"
            raise ReviewError(
                f"Could not fetch PR #{pr}: {detail}. "
                "Check that gh is authenticated ('gh auth login').",
                code=GH_NOT_AUTHENTICATED,
            )
        return normalize_changed_files(completed.stdout.splitlines())

    if diff:
        command = ["git", "diff", "--name-only", diff]
        try:
            completed = subprocess.run(
                command,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise ReviewError(
                f"git could not diff against '{diff}': {exc}",
                code=REF_NOT_FOUND,
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "git diff failed"
            raise ReviewError(
                f"git could not diff against '{diff}': {detail}",
                code=REF_NOT_FOUND,
            )
        return normalize_changed_files(completed.stdout.splitlines())

    raise ReviewError(
        "Provide a git ref to diff against ('diff') or a pull request number ('pr').",
        code=NO_DIFF_PROVIDED,
    )


def open_index(root: Path) -> sqlite3.Connection:
    """Open the index read-only, mapping a missing/unreadable index to NO_INDEX."""
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        raise ReviewError(
            "Index not found. Run 'cerebrofy build' first.",
            code=NO_INDEX,
        )
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        check_schema_version(conn)
    except (sqlite3.Error, ValueError) as exc:
        raise ReviewError(
            f"Index is not readable: {exc}. Run 'cerebrofy build' first.",
            code=NO_INDEX,
        ) from exc
    return conn


# ---------------------------------------------------------------------------
# Internal context
# ---------------------------------------------------------------------------

@dataclass
class _Context:
    """Blast-radius context shared by several checks for one neuron."""

    neuron: BlastNeuron
    blast: NeuronBlastRadius
    callers: list[BlastNeuron] = field(default_factory=list)

    @property
    def caller_count(self) -> int:
        return len(self.callers)

    @property
    def lobes(self) -> list[str]:
        return sorted({self.neuron.lobe} | {caller.lobe for caller in self.callers})


def _build_contexts(
    conn: sqlite3.Connection,
    neurons: list[BlastNeuron],
    depth: int,
) -> list[_Context]:
    contexts: list[_Context] = []
    for neuron in neurons:
        blast = compute_neuron_blast_radius(neuron, conn, depth=depth)
        callers = list(blast.callers_depth1) + list(blast.callers_depth2)
        contexts.append(_Context(neuron=neuron, blast=blast, callers=callers))
    return contexts


def _finding(
    *,
    check_type: str,
    neuron: str,
    file: str,
    line: int,
    severity: str,
    message: str,
    suggestion: str,
    blast_radius: int = 0,
    has_memory_warning: bool = False,
    uncovered: bool = False,
) -> Finding:
    return Finding(
        check_type=check_type,
        neuron=neuron,
        file=file,
        line=max(0, line),
        severity=severity,
        message=message,
        suggestion=suggestion,
        severity_score=compute_severity_score(
            severity,
            blast_radius,
            has_memory_warning=has_memory_warning,
            uncovered=uncovered,
        ),
        blast_radius=blast_radius,
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _blast_findings(contexts: list[_Context]) -> list[Finding]:
    findings: list[Finding] = []
    for context in contexts:
        if not context.callers:
            continue
        severity = _severity_for_risk(context.blast.risk_label)
        direct = len(context.blast.callers_depth1)
        indirect = len(context.blast.callers_depth2)
        message = (
            f"{context.neuron.name} has {direct} direct and {indirect} indirect "
            f"caller(s) across {context.blast.lobe_spread} lobe(s) "
            f"({', '.join(context.lobes)}). This is a {context.blast.risk_label} "
            "blast radius change."
        )
        suggestion = (
            "Review every caller before merging and update call sites in this change."
            if context.blast.risk_label == "HIGH"
            else "Verify the affected callers still behave correctly after this change."
        )
        findings.append(
            _finding(
                check_type="blast_radius",
                neuron=context.neuron.name,
                file=context.neuron.file,
                line=context.neuron.line_start,
                severity=severity,
                message=message,
                suggestion=suggestion,
                blast_radius=context.caller_count,
                uncovered=not context.blast.covering_tests,
            )
        )
    return findings


def _severity_for_risk(risk_label: str) -> str:
    if risk_label == "HIGH":
        return SEVERITY_ERROR
    if risk_label == "MEDIUM":
        return SEVERITY_WARNING
    return SEVERITY_INFO


def _memory_findings(
    context: _Context,
    cerebrofy_dir: Path,
) -> tuple[list[Finding], bool]:
    """Return (findings, memory_store_unavailable)."""
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not memories_db.exists():
        return [], False

    try:
        conn = sqlite3.connect(f"file:{memories_db}?mode=ro", uri=True)
        try:
            warnings = list_memories(
                conn,
                neuron_id=context.neuron.id,
                type_filter="warning",
                include_stale=False,
            )
            decisions = list_memories(
                conn,
                neuron_id=context.neuron.id,
                type_filter="decision",
                include_stale=False,
            )
            if not decisions:
                lobe_decisions = list_memories(
                    conn,
                    lobe=context.neuron.lobe,
                    type_filter="decision",
                    include_stale=False,
                )
                decisions = [
                    memory
                    for memory in lobe_decisions
                    if context.neuron.name in f"{memory.title} {memory.body}"
                ]
        finally:
            conn.close()
    except (sqlite3.Error, OSError, TypeError, ValueError, KeyError):
        # Storage failures and malformed memory rows degrade gracefully; anything
        # else is a genuine bug and must propagate.
        return [], True

    findings: list[Finding] = []
    for memory in warnings:
        findings.append(_memory_finding(context, memory, warning=True))
    for memory in decisions[:5]:
        findings.append(_memory_finding(context, memory, warning=False))
    return findings, False


def _memory_finding(context: _Context, memory: Memory, *, warning: bool) -> Finding:
    try:
        created = datetime.datetime.fromtimestamp(
            memory.created_ts, tz=datetime.timezone.utc
        ).date().isoformat()
    except (OverflowError, OSError, TypeError, ValueError):
        created = "unknown date"
    body = memory.body.strip()
    if len(body) > _MEMORY_BODY_LIMIT:
        body = body[:_MEMORY_BODY_LIMIT].rstrip() + "…"
    kind = "Memory warning" if warning else "Past decision"
    author = memory.author or "unknown"
    return _finding(
        check_type="memory_violation",
        neuron=context.neuron.name,
        file=context.neuron.file,
        line=context.neuron.line_start,
        severity=SEVERITY_WARNING if warning else SEVERITY_INFO,
        message=(
            f"{kind} recorded on {created} by {author}: \"{memory.title}\" — {body}"
        ),
        suggestion=(
            "Honor the recorded decision, or update the memory if it no longer applies."
            if warning
            else "Check this change against the recorded decision and update the memory if superseded."
        ),
        blast_radius=context.caller_count,
        has_memory_warning=warning,
        uncovered=not context.blast.covering_tests,
    )


def _arch_findings(
    *,
    root: Path,
    conn: sqlite3.Connection,
    changed_files: list[str],
    contexts: list[_Context],
) -> tuple[list[Finding], list[str]]:
    skipped: list[str] = []
    try:
        rules = load_arch_rules(root)
    except RulesError as exc:
        return [], [f"architecture rules (invalid arch-rules.yaml: {exc})"]
    except Exception as exc:  # YAML parser errors, unreadable file, ...  # noqa: BLE001
        return [], [f"architecture rules (invalid arch-rules.yaml: {exc})"]
    if rules is None:
        return [], ["architecture rules (no .cerebrofy/arch-rules.yaml)"]
    if not rules.rules:
        return [], []

    lobes: dict[str, str] = {}
    try:
        lobes = load_config(root / ".cerebrofy" / "config.yaml").lobes
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")
    priority_lobes: frozenset[str] = frozenset()
    try:
        from cerebrofy.intent.loader import sprint_priority_lobes

        priority_lobes = sprint_priority_lobes(root / ".cerebrofy")
    except Exception as exc:  # noqa: BLE001
        priority_lobes = frozenset()

    try:
        result = run_arch_check(
            rules,
            conn,
            lobes,
            repo_root=root,
            changed_files=frozenset(changed_files),
            priority_lobes=priority_lobes,
        )
    except Exception as exc:  # noqa: BLE001
        return [], [f"architecture rules (checker failed: {exc})"]

    for rule_name, error in result.config_errors:
        skipped.append(f"architecture rule '{rule_name}' ({error})")

    descriptions = {rule.name: rule.description for rule in rules.rules}
    contexts_by_file: dict[str, list[_Context]] = {}
    for context in contexts:
        contexts_by_file.setdefault(context.neuron.file, []).append(context)

    findings: list[Finding] = []
    for violation in (*result.error_violations, *result.warning_violations):
        matching = contexts_by_file.get(violation.file, [])
        blast_radius = matching[0].caller_count if matching else 0
        uncovered = not any(context.blast.covering_tests for context in matching)
        description = descriptions.get(violation.rule_name, "")
        findings.append(
            _finding(
                check_type="arch_rule",
                neuron=violation.src_name or violation.location,
                file=violation.file,
                line=violation.line,
                severity=violation.severity,
                message=(
                    f"Architecture rule '{violation.rule_name}' violated: "
                    f"{violation.detail} ({violation.location})"
                ),
                suggestion=fix_hint(violation.kind, description),
                blast_radius=blast_radius,
                uncovered=uncovered,
            )
        )
    return findings, skipped


def _coverage_findings(
    *,
    root: Path,
    conn: sqlite3.Connection,
    contexts: list[_Context],
) -> tuple[list[Finding], list[str]]:
    try:
        covered, source = _detect_covered_neurons(root, conn)
    except Exception as exc:  # noqa: BLE001
        return [], [f"coverage gaps (could not detect coverage: {exc})"]

    findings: list[Finding] = []
    for context in contexts:
        if context.neuron.id in covered:
            continue
        severity = _severity_for_risk(context.blast.risk_label)
        findings.append(
            _finding(
                check_type="coverage_gap",
                neuron=context.neuron.name,
                file=context.neuron.file,
                line=context.neuron.line_start,
                severity=severity,
                message=(
                    f"{context.neuron.name} has no {source} test coverage "
                    f"({context.caller_count} caller(s), risk: "
                    f"{context.blast.risk_label})."
                ),
                suggestion=(
                    "Add tests that exercise this neuron and its callers before merging."
                ),
                blast_radius=context.caller_count,
                uncovered=True,
            )
        )
    return findings, []


def _caller_update_findings(
    contexts: list[_Context],
    *,
    changed_files: list[str],
) -> list[Finding]:
    changed_ids = {context.neuron.id for context in contexts}
    changed_file_set = set(changed_files)
    findings: list[Finding] = []
    for context in contexts:
        missing = [
            caller
            for caller in context.blast.callers_depth1
            if caller.id not in changed_ids
            and caller.file not in changed_file_set
            and not caller.file.startswith("tests/")
            and not caller.id.startswith("external::")
        ]
        if not missing:
            continue
        shown = ", ".join(
            f"{caller.file}::{caller.name} (line {caller.line_start})"
            for caller in missing[:5]
        )
        more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
        findings.append(
            _finding(
                check_type="missing_caller_update",
                neuron=context.neuron.name,
                file=context.neuron.file,
                line=context.neuron.line_start,
                severity=SEVERITY_WARNING,
                message=(
                    f"{len(missing)} direct caller(s) are not updated in this change: "
                    f"{shown}{more}."
                ),
                suggestion=(
                    "Update or explicitly verify these call sites; a signature or "
                    "behaviour change here can break them."
                ),
                blast_radius=context.caller_count,
                uncovered=not context.blast.covering_tests,
            )
        )
    return findings


@dataclass
class _GraphSnapshot:
    """Node/edge/lobe data loaded once for health and coupling checks."""

    node_files: dict[str, str]
    health_lobes: dict[str, str]
    edges: list[tuple[str, str]]


def _load_graph_snapshot(
    conn: sqlite3.Connection,
    contexts: list[_Context],
    root: Path,
) -> _GraphSnapshot:
    """Load the graph data shared by the health-delta and coupling checks."""
    from cerebrofy.health.metrics import _lobe_for_file

    node_files: dict[str, str] = {}
    health_lobes: dict[str, str] = {}
    for node_id, file_path, node_type in conn.execute(
        "SELECT id, file, type FROM nodes"
    ).fetchall():
        key = str(node_id)
        node_files[key] = str(file_path)
        # Match the SQL ``type != 'module'`` filter (NULL types are excluded).
        if node_type is not None and node_type != "module":
            health_lobes[key] = _lobe_for_file(str(file_path), {})

    # Prefer the configured lobe map when available; ad-hoc DBs keep the
    # path-derived fallback computed above.
    if contexts and health_lobes:
        try:
            config = load_config(root / ".cerebrofy" / "config.yaml")
            health_lobes = {
                node_id: _lobe_for_file(node_files[node_id], config.lobes)
                for node_id in health_lobes
            }
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")
    edges = [
        (str(src), str(dst))
        for src, dst in conn.execute(
            "SELECT src_id, dst_id FROM edges WHERE rel_type != 'RUNTIME_BOUNDARY'"
        ).fetchall()
    ]
    return _GraphSnapshot(
        node_files=node_files,
        health_lobes=health_lobes,
        edges=edges,
    )


def _compute_health_delta(
    snapshot: _GraphSnapshot,
    contexts: list[_Context],
) -> HealthDelta:
    """Return coupling delta and average blast radius for the changed neurons."""
    changed_ids = {context.neuron.id for context in contexts}
    total_edges = 0
    total_cross = 0
    changed_edges = 0
    changed_cross = 0
    for src, dst in snapshot.edges:
        if src not in snapshot.health_lobes or dst not in snapshot.health_lobes:
            continue
        total_edges += 1
        is_cross = snapshot.health_lobes[src] != snapshot.health_lobes[dst]
        if is_cross:
            total_cross += 1
        if src in changed_ids or dst in changed_ids:
            changed_edges += 1
            if is_cross:
                changed_cross += 1

    overall = total_cross / total_edges if total_edges else 0.0
    local = changed_cross / changed_edges if changed_edges else 0.0
    coupling_delta = round(local - overall, 4) if changed_edges else 0.0

    avg_blast = (
        sum(context.caller_count for context in contexts) / len(contexts)
        if contexts
        else 0.0
    )
    return HealthDelta(coupling=coupling_delta, avg_blast=round(avg_blast, 2))


def _coupling_findings(
    contexts: list[_Context],
    snapshot: _GraphSnapshot,
) -> list[Finding]:
    """Flag changed neurons whose immediate edges cross lobe boundaries."""

    def lobe(node_id: str) -> str:
        file_path = snapshot.node_files.get(node_id, "")
        return Path(file_path).parts[0] if file_path else ""

    findings: list[Finding] = []
    for context in contexts:
        touching = [
            (src, dst)
            for src, dst in snapshot.edges
            if context.neuron.id in (src, dst)
        ]
        other_lobes = sorted(
            {
                lobe(src) if dst == context.neuron.id else lobe(dst)
                for src, dst in touching
            }
            - {"", context.neuron.lobe}
        )
        if not other_lobes:
            continue
        severity = SEVERITY_WARNING if len(other_lobes) >= 3 else SEVERITY_INFO
        findings.append(
            _finding(
                check_type="coupling",
                neuron=context.neuron.name,
                file=context.neuron.file,
                line=context.neuron.line_start,
                severity=severity,
                message=(
                    f"{context.neuron.name} is coupled to {len(other_lobes)} other "
                    f"lobe(s): {', '.join(other_lobes)}. "
                    "This change adds cross-lobe coupling."
                ),
                suggestion=(
                    "Consider routing this dependency through an interface or "
                    "injecting it at the boundary instead of calling across lobes."
                ),
                blast_radius=context.caller_count,
                uncovered=not context.blast.covering_tests,
            )
        )
    return findings


def _silo_signals(
    contexts: list[_Context],
    root: Path,
    conn: sqlite3.Connection,
) -> tuple[list[SuggestedReviewer], list[Finding]]:
    """Return suggested reviewers and knowledge-silo findings from git blame."""
    blame_cache: dict[str, dict[int, str]] = {}
    line_end_by_id = {
        str(node_id): int(line_end or line_start or 1)
        for node_id, line_start, line_end in conn.execute(
            "SELECT id, line_start, line_end FROM nodes"
        ).fetchall()
    }

    reviewers: dict[str, SuggestedReviewer] = {}
    findings: list[Finding] = []
    for context in contexts:
        if context.neuron.file not in blame_cache:
            blame_cache[context.neuron.file] = _blame_file(context.neuron.file, root)
        blame = blame_cache[context.neuron.file]
        if not blame:
            continue
        line_end = line_end_by_id.get(context.neuron.id, context.neuron.line_start)
        authors, primary, pct = _authors_for_range(
            blame, context.neuron.line_start, line_end
        )
        if primary in ("", "unknown"):
            continue
        reason = (
            f"sole author of {context.neuron.name} "
            f"({context.caller_count} caller(s), {pct:.0%} of lines)"
            if len(authors) == 1
            else f"primary author of {context.neuron.name} ({pct:.0%} of lines)"
        )
        reviewers.setdefault(
            primary,
            SuggestedReviewer(email=primary, lobe=context.neuron.lobe, reason=reason),
        )
        if len(authors) != 1:
            continue
        silo_score = round(context.caller_count / max(len(authors), 1), 2)
        severity = SEVERITY_WARNING if context.caller_count >= 5 else SEVERITY_INFO
        findings.append(
            _finding(
                check_type="knowledge_silo",
                neuron=context.neuron.name,
                file=context.neuron.file,
                line=context.neuron.line_start,
                severity=severity,
                message=(
                    f"Only {primary} understands {context.neuron.name} "
                    f"({context.caller_count} caller(s), silo_score={silo_score})."
                ),
                suggestion=f"Add {primary} as a reviewer or schedule knowledge transfer.",
                blast_radius=context.caller_count,
                uncovered=not context.blast.covering_tests,
            )
        )

    return list(reviewers.values()), findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_review(
    *,
    changed_files: list[str],
    conn: sqlite3.Connection,
    root: Path,
    pr: int | None = None,
    diff_ref: str | None = None,
    severity: str = "all",
    depth: int = 2,
    record_session: bool = False,
) -> ReviewReport:
    """Run every available review check for *changed_files*."""
    files = normalize_changed_files(changed_files)
    neurons = neurons_for_changed_files(files, conn)
    contexts = _build_contexts(conn, neurons, depth)

    behaviors: list[Finding] = []
    skipped: list[str] = []

    behaviors.extend(_blast_findings(contexts))
    behaviors.extend(_caller_update_findings(contexts, changed_files=files))

    memory_unavailable = False
    for context in contexts:
        memory_findings, unavailable = _memory_findings(
            context, root / ".cerebrofy"
        )
        behaviors.extend(memory_findings)
        memory_unavailable = memory_unavailable or unavailable
    if memory_unavailable:
        skipped.append("memory warnings (memories.db is unreadable)")

    arch_findings, arch_skipped = _arch_findings(
        root=root,
        conn=conn,
        changed_files=files,
        contexts=contexts,
    )
    behaviors.extend(arch_findings)
    skipped.extend(arch_skipped)

    coverage_findings, coverage_skipped = _coverage_findings(
        root=root,
        conn=conn,
        contexts=contexts,
    )
    behaviors.extend(coverage_findings)
    skipped.extend(coverage_skipped)

    # #22 Epistemic Confidence integration: add confidence metadata to findings
    config = load_config(root / ".cerebrofy" / "config.yaml")
    epistemic_state = compute_epistemic_state(conn, config.tracked_extensions, root)
    for finding in behaviors:
        finding.epistemic_confidence = epistemic_state.overall_confidence

    # #23 Product Intent integration: escalate severity for priority lobes
    try:
        priority_lobes = sprint_priority_lobes(root / ".cerebrofy")
        if priority_lobes:
            for finding in behaviors:
                if finding.neuron_lobe in priority_lobes:
                    finding.severity_score = min(1.0, finding.severity_score * 1.2)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(f"Silent error ignored: {exc}")

    snapshot = _load_graph_snapshot(conn, contexts, root)
    health_delta = _compute_health_delta(snapshot, contexts)
    behaviors.extend(_coupling_findings(contexts, snapshot))

    reviewers, silo_findings = _silo_signals(contexts, root, conn)
    behaviors.extend(silo_findings)

    findings = sort_findings(filter_findings(behaviors, severity))

    neuron_names = {context.neuron.name for context in contexts}
    flagged_neurons = {finding.neuron for finding in findings}
    clean_neurons = max(0, len(neuron_names) - len(flagged_neurons))
    max_blast = max((context.caller_count for context in contexts), default=0)

    report = ReviewReport(
        files_changed=len(files),
        neurons_changed=len(neurons),
        findings=findings,
        suggested_reviewers=reviewers,
        health_delta=health_delta,
        skipped_checks=skipped,
        changed_files=files,
        clean_neurons=clean_neurons,
        max_blast_radius=max_blast,
    )
    target = f"PR #{pr}" if pr is not None else (f"diff {diff_ref}" if diff_ref else None)
    report.summary = format_summary(report, target=target)

    if record_session:
        _record_review_session(root, report, pr=pr, diff_ref=diff_ref)

    return report


def review_diff_or_pr(
    *,
    root: Path,
    diff: str | None = None,
    pr: int | None = None,
    severity: str = "all",
    depth: int = 2,
    record_session: bool = False,
) -> ReviewReport:
    """Resolve a diff/PR, open the index, and run the review."""
    changed_files = resolve_changed_files(diff=diff, pr=pr, repo_root=root)
    if not changed_files:
        return ReviewReport(
            files_changed=0,
            neurons_changed=0,
            summary=format_summary(
                ReviewReport(files_changed=0, neurons_changed=0),
                target=f"PR #{pr}" if pr is not None else f"diff {diff}",
            ),
        )
    conn = open_index(root)
    try:
        return run_review(
            changed_files=changed_files,
            conn=conn,
            root=root,
            pr=pr,
            diff_ref=diff,
            severity=severity,
            depth=depth,
            record_session=record_session,
        )
    finally:
        conn.close()


def _record_review_session(
    root: Path,
    report: ReviewReport,
    *,
    pr: int | None,
    diff_ref: str | None,
) -> None:
    """Best-effort recording of the review as a session event (Idea #11)."""
    try:
        from cerebrofy.session.middleware import SessionMiddleware

        middleware = SessionMiddleware(root)
        try:
            if not middleware.is_recording():
                return
            middleware.record(
                "cerebrofy_review",
                {"pr": pr, "diff": diff_ref},
                [SimpleNamespace(text=report.summary)],
            )
        finally:
            middleware.close()
    except Exception as exc:  # noqa: BLE001
        return
