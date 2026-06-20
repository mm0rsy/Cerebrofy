"""Budget-aware greedy context packer.

Algorithm:
1. Embed task → KNN seeds via hybrid_search (top-20).
2. Score each candidate: semantic * 0.6 + graph_proximity * 0.4.
3. Sort by score desc, greedy-pack into budget with tier degradation:
   full_source → signature_only → lobe_summary → name_only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.context.scorer import compute_relevance
from cerebrofy.context.token_counter import count_tokens, tokens_for_source
from cerebrofy.search.hybrid import MatchedNeuron

TIER_FULL = "full_source"
TIER_SIG = "signature_only"
TIER_LOBE = "lobe_summary"
TIER_NAME = "name_only"

# Approximate token cost per tier when source reading fails/is skipped
_NAME_ONLY_TOKENS = 12


@dataclass
class ContextNeuron:
    """One neuron in the packed context plan."""

    id: str
    name: str
    file: str
    line_start: int
    line_end: int
    relevance_score: float
    inclusion_tier: str
    source: str            # "semantic" | "graph_expansion"
    content: str           # actual text included in context
    tokens: int


@dataclass
class EpistemicInfo:
    """Basic graph staleness metadata (simplified #22 placeholder)."""

    confidence: float
    graph_age_hours: float
    caveats: list[str]
    recommendation: str


@dataclass
class ContextPlan:
    """Result of one optimize_context() call."""

    task: str
    token_budget: int
    tokens_used: int
    neurons: list[ContextNeuron] = field(default_factory=list)
    lobe_summaries_included: list[str] = field(default_factory=list)
    truncated_count: int = 0
    epistemic: EpistemicInfo | None = None


def _lobe_from_file(file: str) -> str:
    parts = Path(file).parts
    return parts[0] if len(parts) > 1 else ""


def _read_lobe_summary(lobe: str, root: Path) -> tuple[str, int]:
    """Read the lobe markdown summary. Returns (text, tokens)."""
    summary_path = root / ".cerebrofy" / "lobes" / f"{lobe}_lobe.md"
    if not summary_path.exists():
        # Try docs/ path used by some versions
        summary_path = root / "docs" / "cerebrofy" / f"{lobe}_lobe.md"
    if not summary_path.exists():
        return "", 0
    text = summary_path.read_text(encoding="utf-8", errors="replace")
    return text, count_tokens(text)


def _signature_text(name: str, signature: str | None, docstring: str | None) -> str:
    parts = []
    if signature:
        parts.append(signature)
    if docstring:
        parts.append(f'    """{docstring[:200]}"""')
    return "\n".join(parts) if parts else f"# {name}"


def _compute_epistemic(db_path: Path) -> EpistemicInfo:
    """Compute basic graph staleness info from DB modification time."""
    try:
        mtime = db_path.stat().st_mtime
        age_hours = (time.time() - mtime) / 3600.0
    except OSError:
        age_hours = 0.0

    caveats: list[str] = []
    recommendation = "Index is fresh."
    confidence = 1.0

    if age_hours > 24:
        caveats.append(f"Index is {age_hours:.0f}h old — callers may have changed.")
        recommendation = "Run 'cerebrofy build' for full confidence."
        confidence = max(0.5, 1.0 - (age_hours / 168.0))  # decay over 1 week

    return EpistemicInfo(
        confidence=round(confidence, 2),
        graph_age_hours=round(age_hours, 1),
        caveats=caveats,
        recommendation=recommendation,
    )


def optimize_context(
    task: str,
    db_path: Path,
    config_path: Path,
    budget: int = 8000,
    model: str = "auto",
    repo_root: Path | None = None,
) -> ContextPlan:
    """Build a budget-constrained context plan for the given task."""
    from cerebrofy.config.loader import load_config
    from cerebrofy.search.hybrid import embed_query, hybrid_search

    root = repo_root or db_path.parent.parent.parent
    config = load_config(config_path)

    # Step 1: embed task + KNN + BFS via hybrid_search (top-20 seeds)
    embedding = embed_query(task, config.embedding_model)
    result = hybrid_search(
        query=task,
        db_path=db_path,
        embedding=embedding,
        top_k=20,
        lobes=config.lobes,
        repo_root=root,
    )

    # Step 2: score all candidates
    scored: list[tuple[float, MatchedNeuron, bool]] = []
    for n in result.matched_neurons:
        scored.append((compute_relevance(n.similarity, is_seed=True), n, True))
    for n in result.blast_radius:
        scored.append((compute_relevance(0.0, is_seed=False), n, False))

    scored.sort(key=lambda x: -x[0])

    # Step 3: greedy pack with tier degradation
    plan = ContextPlan(task=task, token_budget=budget, tokens_used=0)
    used_lobes: set[str] = set()
    lobe_summary_cache: dict[str, tuple[str, int]] = {}

    for score, neuron, is_seed in scored:
        remaining = budget - plan.tokens_used
        if remaining <= _NAME_ONLY_TOKENS:
            plan.truncated_count += 1
            continue

        src_origin = "semantic" if is_seed else "graph_expansion"
        lobe = _lobe_from_file(neuron.file)

        line_start = neuron.line_start or 1
        line_end = neuron.line_end or line_start

        # Try tiers in order: full → sig → lobe → name
        placed = False
        for tier in (TIER_FULL, TIER_SIG, TIER_LOBE, TIER_NAME):
            if tier == TIER_FULL:
                content, tokens = tokens_for_source(
                    neuron.file, line_start, line_end, str(root), model
                )
                if not content:
                    continue

            elif tier == TIER_SIG:
                content = _signature_text(neuron.name, neuron.signature, neuron.docstring)
                tokens = count_tokens(content, model)

            elif tier == TIER_LOBE:
                if not lobe:
                    continue
                if lobe not in lobe_summary_cache:
                    lobe_summary_cache[lobe] = _read_lobe_summary(lobe, root)
                content, tokens = lobe_summary_cache[lobe]
                if not content or lobe in used_lobes:
                    continue

            else:  # name_only
                content = f"{neuron.file}:{line_start}::{neuron.name}"
                tokens = count_tokens(content, model)

            if tokens <= remaining:
                plan.neurons.append(ContextNeuron(
                    id=neuron.id,
                    name=neuron.name,
                    file=neuron.file,
                    line_start=line_start,
                    line_end=line_end,
                    relevance_score=round(score, 4),
                    inclusion_tier=tier,
                    source=src_origin,
                    content=content,
                    tokens=tokens,
                ))
                plan.tokens_used += tokens
                if tier == TIER_LOBE and lobe:
                    used_lobes.add(lobe)
                    plan.lobe_summaries_included.append(lobe)
                placed = True
                break

        if not placed:
            plan.truncated_count += 1

    plan.epistemic = _compute_epistemic(db_path)
    return plan
