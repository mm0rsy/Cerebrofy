"""Plan orchestration for the natural-language refactor planner (Idea #12).

Coordinates the pipeline for both entry points (CLI and MCP):
extract a cohesive cluster → map files into the new module → sequence the
migration → attach graph-derived risk/context → hand off to a formatter.

Integrations with completed features (all degrade gracefully):
  #01 blast radius — per-step containment check and plan-level risk label.
  #05 agent memory — past decisions/warnings surfaced as plan context.
  #07 refactor impact — per-step impact prediction (reused, not reimplemented).
  #23 product intent — ``avoid_patterns`` shape the recommendations.

Deferred (not on this branch):
  TODO(integration-11): record plan execution as a session (session recorder).
  TODO(integration-17): review execution against this plan (review copilot).
  TODO(integration-24): read synthesized failure patterns and skip risky steps.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.analysis.blast_radius import BlastNeuron, compute_neuron_blast_radius
from cerebrofy.analysis.impact import ImpactNeuron, compute_impact
from cerebrofy.config.loader import PlanningConfig, _GENERIC_MODULE_WORDS
from cerebrofy.context.optimizer import optimize_context
from cerebrofy.errors import CLUSTER_TOO_LARGE, CLUSTER_TOO_SMALL
from cerebrofy.errors import NO_INDEX as NO_INDEX  # re-exported for CLI/MCP callers
from cerebrofy.intent.loader import load_intent
from cerebrofy.memory.search import recall_memories
from cerebrofy.memory.store import open_memories_db
from cerebrofy.planning.extractor import (
    DEFAULT_TOP_K,
    ClusterNeuron,
    ClusterSizeError,
    NeuronCluster,
    find_extraction_cluster,
)
from cerebrofy.planning.sequence import MigrationStep, build_migration_steps

# Error codes (spec — shared by the CLI and MCP surfaces) are defined once in
# :mod:`cerebrofy.errors` and re-exported here for callers that import them
# from this module (back-compat).

_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# Words that describe the shape of an extraction rather than its new name.
# Single source of truth lives in cerebrofy.config.loader (imported above);
# derive_module_name() defaults generic_words to this set when None.

_NAMED_MODULE_RE = re.compile(
    r"\binto\s+(?:its\s+own\s+|a\s+|an\s+|the\s+)?(?:new\s+)?`?([a-z][a-z0-9_.-]*)`?"
    r"\s+(?:module|package|service|library|directory|layer)\b",
    re.IGNORECASE,
)
_INTO_TOKEN_RE = re.compile(
    r"\binto\s+(?:its\s+own\s+|a\s+|an\s+|the\s+)?(?:new\s+)?`?([a-z][a-z0-9_./-]*)`?",
    re.IGNORECASE,
)


class PlanError(Exception):
    """A planner failure carrying one of the spec's error codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RefactorPlan:
    """Structured result of one planner run.

    ``cluster``/``callers_to_update``/``steps``/``estimated_hours``/
    ``files_affected`` are the spec's output schema; the remaining fields are
    Markdown-only context (warnings, memories, execution handoff).
    """

    description: str
    cluster: list[ClusterNeuron]
    seeds: list[ClusterNeuron]
    callers_to_update: list[ClusterNeuron]
    new_module: str
    proposed_files: list[str]
    file_map: dict[str, str]
    steps: list[MigrationStep]
    estimated_hours: float
    files_affected: int
    blast_radius_label: str = "LOW"
    memory_context: list[str] = field(default_factory=list)
    avoid_pattern_warnings: list[str] = field(default_factory=list)
    runtime_boundary_callers: list[str] = field(default_factory=list)
    handoff_summary: str | None = None


@dataclass(frozen=True)
class PlanContext:
    """Shared inputs for the refactor-planning pipeline.

    Bundled once in :func:`build_refactor_plan` and handed to each pipeline
    step so individual steps receive only the data they need rather than a
    long positional argument list. The connection lifecycle stays with the
    caller; ``build_refactor_plan`` never closes the injected connection.
    """

    repo_root: Path
    conn: sqlite3.Connection
    description: str
    embedding: list[float]
    config: PlanningConfig
    top_k: int
    config_path: Path
    dry_run: bool


# ---------------------------------------------------------------------------
# Module naming (deterministic, language-neutral)
# ---------------------------------------------------------------------------

def _sanitize_module(token: str) -> str:
    """Normalise a module-name candidate to a snake_case identifier."""
    token = token.strip().strip("`").replace("\\", "/").strip("/")
    tail = token.split("/")[-1] if token else ""
    tail = re.sub(r"[^a-zA-Z0-9_]+", "_", tail).strip("_").lower()
    return tail


def _graph_derived_module(cluster: list[ClusterNeuron]) -> str:
    """Fall back to the cluster's dominant parent directory (or file stem)."""
    parents = [
        Path(n.file).parent.name
        for n in cluster
        if n.file and Path(n.file).parent.name not in ("", ".")
    ]
    if parents:
        counts = Counter(parents)
        return max(counts, key=lambda name: (counts[name], name))
    stems = [Path(n.file).stem for n in cluster if n.file and Path(n.file).stem]
    if stems:
        counts = Counter(stems)
        return max(counts, key=lambda name: (counts[name], name))
    return "extracted"


def derive_module_name(
    description: str,
    cluster: list[ClusterNeuron],
    *,
    generic_words: frozenset[str] | None = None,
) -> str:
    """Derive the proposed new module name from the description or graph.

    Examples: "extract the payment logic into a payments service" → ``payments``;
    "move database code into a db/ module" → ``db``. When the description names
    no target, the dominant parent directory inside the cluster is used.

    *generic_words* overrides the default filter set for tokens that describe
    the extraction shape rather than a concrete name. When ``None`` (the
    default) the module-level ``_GENERIC_MODULE_WORDS`` from
    ``cerebrofy.config.loader`` is used — no literal is duplicated.
    """
    if generic_words is None:
        generic_words = _GENERIC_MODULE_WORDS
    for pattern in (_NAMED_MODULE_RE, _INTO_TOKEN_RE):
        match = pattern.search(description)
        if match is None:
            continue
        candidate = _sanitize_module(match.group(1))
        if candidate and candidate not in generic_words:
            return candidate
    fallback = _sanitize_module(_graph_derived_module(cluster))
    return fallback or "extracted"


def map_cluster_files(
    cluster: list[ClusterNeuron],
    new_module: str,
) -> dict[str, str]:
    """Map each source file in the cluster to its target path in the new module."""
    file_map: dict[str, str] = {}
    used: set[str] = set()
    for source_file in sorted({n.file for n in cluster if n.file}):
        suffix = Path(source_file).suffix
        stem = Path(source_file).stem
        target = f"{new_module}/{stem}{suffix}"
        counter = 2
        while target in used:
            target = f"{new_module}/{stem}_{counter}{suffix}"
            counter += 1
        used.add(target)
        file_map[source_file] = target
    return file_map


# ---------------------------------------------------------------------------
# Completed-feature integrations (each degrades gracefully when data is absent)
# ---------------------------------------------------------------------------

def _blast_radius_label(
    conn: sqlite3.Connection,
    cluster: list[ClusterNeuron],
) -> str:
    """Aggregate the highest #01 blast-radius label across moved neurons."""
    label = "LOW"
    for neuron in cluster:
        blast_neuron = BlastNeuron(
            id=neuron.id,
            name=neuron.name,
            file=neuron.file,
            line_start=neuron.line_start or 1,
            lobe=Path(neuron.file).parts[0] if Path(neuron.file).parts else "root",
        )
        try:
            result = compute_neuron_blast_radius(blast_neuron, conn, depth=2)
        except (sqlite3.Error, ValueError):
            continue  # partial/legacy index — containment check is best-effort
        if _RISK_ORDER.get(result.risk_label, 0) > _RISK_ORDER.get(label, 0):
            label = result.risk_label
    return label


def _impact_for(
    conn: sqlite3.Connection,
    neuron_id: str,
    repo_root: Path,
) -> ImpactNeuron | None:
    """Build the #07 impact input for a cluster neuron id."""
    row = conn.execute(
        "SELECT id, name, file, line_start, line_end FROM nodes WHERE id = ?",
        (neuron_id,),
    ).fetchone()
    if row is None:
        return None
    node_id, name, file, line_start, line_end = row
    parts = Path(file).parts
    return ImpactNeuron(
        id=node_id,
        name=name,
        file=file,
        line_start=line_start or 1,
        line_end=line_end or (line_start or 1),
        lobe=parts[0] if parts else "root",
    )


def annotate_steps_with_impact(
    steps: list[MigrationStep],
    conn: sqlite3.Connection,
    repo_root: Path,
) -> tuple[list[MigrationStep], list[str]]:
    """Attach #07 impact predictions to steps; collect memory warnings.

    Returns (annotated_steps, warning_memory_titles). Impact prediction runs on
    the first neuron of each step — enough to size the step without making
    plan generation quadratic.
    """
    annotated: list[MigrationStep] = []
    memory_titles: list[str] = []
    for step in steps:
        neuron = (
            _impact_for(conn, step.neurons_affected[0], repo_root)
            if step.neurons_affected and not step.callers_break
            else None
        )
        if neuron is None:
            annotated.append(step)
            continue
        try:
            result = compute_impact(
                neuron,
                conn,
                depth=2,
                show_tests=False,
                cerebrofy_dir=repo_root / ".cerebrofy",
            )
        except (sqlite3.Error, ValueError):
            annotated.append(step)
            continue
        memory_titles.extend(result.memory_warnings)
        if result.complexity_rating == "LOW":
            annotated.append(step)
            continue
        callers = sum(len(neurons) for neurons in result.callers_by_depth.values())
        annotated.append(MigrationStep(
            step_number=step.step_number,
            description=(
                f"{step.description} — impact: {result.complexity_rating} "
                f"({callers} callers, {result.lobe_spread} lobe(s))"
            ),
            neurons_affected=list(step.neurons_affected),
            callers_break=step.callers_break,
        ))
    return annotated, sorted(set(memory_titles))


def _memory_context(
    repo_root: Path,
    embedding: list[float],
) -> list[str]:
    """Recall #05 memories relevant to the refactoring description."""
    # TODO(integration-24): also merge synthesized patterns from the
    # cross-session synthesizer and skip steps that historically fail.
    cerebrofy_dir = repo_root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return []
    try:
        conn = open_memories_db(cerebrofy_dir)
        try:
            results = recall_memories(conn, embedding, limit=5)
        finally:
            conn.close()
    except Exception:
        return []
    return [f"{memory.type}: {memory.title}" for memory, _score in results]


def _avoid_pattern_warnings(
    repo_root: Path,
    cluster: list[ClusterNeuron],
    new_module: str,
) -> list[str]:
    """#23 intent.yaml: warn when the extraction touches an avoided pattern."""
    try:
        intent = load_intent(repo_root / ".cerebrofy")
    except Exception:
        return []
    if intent is None or intent.architecture is None:
        return []

    haystacks = [new_module.lower()] + sorted({n.file.lower() for n in cluster})
    warnings: list[str] = []
    for pattern in intent.architecture.avoid_patterns:
        needle = pattern.strip().lower()
        if needle and any(needle in haystack for haystack in haystacks):
            warnings.append(
                f"avoid_pattern '{pattern}' matches the affected code — "
                "reconsider the proposed extraction"
            )
    return warnings


def _execution_handoff(
    description: str,
    db_path: Path,
    config_path: Path,
    repo_root: Path,
) -> str | None:
    """Prepare an #02 optimized context window for the executing agent."""
    # TODO(integration-11): record the approved execution as a session.
    # TODO(integration-17): after execution, review it against this plan.
    try:
        context_plan = optimize_context(
            task=description,
            db_path=db_path,
            config_path=config_path,
            repo_root=repo_root,
        )
    except Exception:
        return None
    return (
        f"{len(context_plan.neurons)} neuron(s) packed into "
        f"{context_plan.tokens_used}/{context_plan.token_budget} tokens — "
        "execution handoff ready for the calling agent"
    )


# ---------------------------------------------------------------------------
# Pipeline steps (each independently testable; orchestrated by
# build_refactor_plan). Steps receive only the PlanContext plus the data
# produced by the immediately preceding step(s) — never the whole pipeline.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanContextResult:
    """Output of ``_collect_context_step``: #05 memory + #23 intent signals."""

    memory_context: list[str]
    avoid_pattern_warnings: list[str]


def _extract_cluster_step(ctx: PlanContext) -> NeuronCluster:
    """Phase #12/#01: extract the cohesive neuron cluster with config-bound checks.

    Translates ``ClusterSizeError`` into a ``PlanError`` carrying the spec error
    code (``CLUSTER_TOO_SMALL`` / ``CLUSTER_TOO_LARGE``). The actual size bounds
    from *ctx.config* flow through to the error message via ClusterSizeError.
    """
    try:
        return find_extraction_cluster(
            ctx.conn,
            ctx.embedding,
            top_k=ctx.top_k,
            min_size=ctx.config.min_cluster_size,
            max_size=ctx.config.max_cluster_size,
        )
    except ClusterSizeError as exc:
        if exc.size < exc.low:
            raise PlanError(
                CLUSTER_TOO_SMALL,
                f"Only {exc.size} neuron(s) matched the description — refine the query.",
            ) from exc
        raise PlanError(
            CLUSTER_TOO_LARGE,
            f"{exc.size} neurons matched — more than the {exc.high} supported; "
            "scope the description more narrowly.",
        ) from exc


def _name_module_step(ctx: PlanContext, cluster: NeuronCluster) -> str:
    """Derive the new module name from the description, honoring config words."""
    return derive_module_name(
        ctx.description,
        cluster.neurons,
        generic_words=ctx.config.generic_module_words,
    )


def _map_files_step(
    ctx: PlanContext,
    cluster: NeuronCluster,
    module: str,
) -> dict[str, str]:
    """Map every cluster source file to its target path in the new module."""
    return map_cluster_files(cluster.neurons, module)


def _sequence_step(
    ctx: PlanContext,
    cluster: NeuronCluster,
    module: str,
    file_map: dict[str, str],
) -> list[MigrationStep]:
    """Build the dependency-safe, reverse-topo-ordered migration steps."""
    return build_migration_steps(
        cluster=cluster.neurons,
        callers=cluster.external_callers,
        runtime_boundary_callers=cluster.runtime_boundary_callers,
        conn=ctx.conn,
        new_module=module,
        file_map=file_map,
    )


def _annotate_impact_step(
    ctx: PlanContext,
    steps: list[MigrationStep],
) -> tuple[list[MigrationStep], list[str]]:
    """Attach #07 impact predictions to steps; return warnings for memory."""
    return annotate_steps_with_impact(steps, ctx.conn, ctx.repo_root)


def _blast_label_step(
    ctx: PlanContext,
    cluster: NeuronCluster,
    steps: list[MigrationStep],
) -> str:
    """#01: plan-level blast-radius risk label across the moved neurons."""
    # ``steps`` is part of the blast integration's scope (per-step containment
    # check, Idea #12); the current implementation surfaces the plan-level label.
    return _blast_radius_label(ctx.conn, cluster.neurons)


def _collect_context_step(
    ctx: PlanContext,
    cluster: NeuronCluster,
    module: str,
    impact_warnings: list[str],
) -> PlanContextResult:
    """Gather #05 memory context + impact warnings + #23 intent avoid patterns."""
    memory_context = _memory_context(ctx.repo_root, ctx.embedding)
    memory_context.extend(f"warning: {title}" for title in impact_warnings)
    memory_context = list(dict.fromkeys(memory_context))
    avoid_warnings = _avoid_pattern_warnings(
        ctx.repo_root, cluster.neurons, module
    )
    return PlanContextResult(
        memory_context=memory_context,
        avoid_pattern_warnings=avoid_warnings,
    )


def _estimate_step(
    cluster: NeuronCluster,
    file_map: dict[str, str],
) -> tuple[float, int]:
    """Estimate effort (#spec formula) and count affected files.

    Pure function of cluster/caller/file data — no DB or filesystem access.
    """
    files_affected = len(
        {n.file for n in cluster.neurons if n.file}
        | set(file_map.values())
        | {c.file for c in cluster.external_callers if c.file}
    )
    estimated_hours = round(
        0.5
        + 0.1 * len(cluster.neurons)
        + 0.05 * len(cluster.external_callers)
        + 0.25 * len(file_map),
        1,
    )
    return estimated_hours, files_affected


def _handoff_step(ctx: PlanContext) -> str | None:
    """Prepare the #02 optimized context-window handoff (gated by dry_run).

    Delegates to ``_execution_handoff`` so tests can monkeypatch that seam;
    returns None for dry runs (no optimizer invocation).
    """
    if ctx.dry_run:
        return None
    return _execution_handoff(
        ctx.description,
        ctx.repo_root / ".cerebrofy" / "db" / "cerebrofy.db",
        ctx.config_path,
        ctx.repo_root,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_refactor_plan(
    *,
    description: str,
    conn: sqlite3.Connection,
    embedding: list[float],
    repo_root: Path,
    config: PlanningConfig | None = None,
    config_path: Path | None = None,
    top_k: int = DEFAULT_TOP_K,
    dry_run: bool = True,
) -> RefactorPlan:
    """Generate a graph-aware refactoring plan for *description*.

    The query *embedding* is pre-computed by the entry point so this function
    stays independent of the embedding backend. ``dry_run=False`` only adds an
    execution-handoff summary — no files are ever written by the planner.

    The *conn* parameter must be a pre-opened read-only connection to the
    cerebrofy.db index. Connection lifecycle is managed by the caller.

    *config* injects planning parameters (cluster size bounds, generic module
    words); it defaults to :class:`~cerebrofy.config.loader.PlanningConfig` so
    callers that don't supply one get the spec's 2..200 range.
    """
    repo_root = Path(repo_root)
    config_path = config_path or (repo_root / ".cerebrofy" / "config.yaml")
    plan_config = config if config is not None else PlanningConfig()

    ctx = PlanContext(
        repo_root=repo_root,
        conn=conn,
        description=description,
        embedding=embedding,
        config=plan_config,
        top_k=top_k,
        config_path=config_path,
        dry_run=dry_run,
    )

    cluster = _extract_cluster_step(ctx)
    new_module = _name_module_step(ctx, cluster)
    file_map = _map_files_step(ctx, cluster, new_module)
    steps = _sequence_step(ctx, cluster, new_module, file_map)
    steps, impact_warnings = _annotate_impact_step(ctx, steps)
    blast_label = _blast_label_step(ctx, cluster, steps)
    context = _collect_context_step(ctx, cluster, new_module, impact_warnings)
    estimated_hours, files_affected = _estimate_step(cluster, file_map)
    handoff = _handoff_step(ctx)

    return RefactorPlan(
        description=description.strip(),
        cluster=cluster.neurons,
        seeds=cluster.seeds,
        callers_to_update=cluster.external_callers,
        new_module=new_module,
        proposed_files=sorted(set(file_map.values())),
        file_map=file_map,
        steps=steps,
        estimated_hours=estimated_hours,
        files_affected=files_affected,
        blast_radius_label=blast_label,
        memory_context=context.memory_context,
        avoid_pattern_warnings=context.avoid_pattern_warnings,
        runtime_boundary_callers=cluster.runtime_boundary_callers,
        handoff_summary=handoff,
    )