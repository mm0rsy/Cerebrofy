"""Output formatters for ContextPlan: JSON, Markdown, Claude XML."""

from __future__ import annotations

import json

from cerebrofy.context.optimizer import ContextPlan


def to_json(plan: ContextPlan) -> str:
    out: dict[str, object] = {
        "task": plan.task,
        "token_budget": plan.token_budget,
        "tokens_used": plan.tokens_used,
        "neurons": [
            {
                "name": n.name,
                "file": n.file,
                "line_start": n.line_start,
                "line_end": n.line_end,
                "relevance_score": n.relevance_score,
                "inclusion_tier": n.inclusion_tier,
                "source": n.source,
                "tokens": n.tokens,
            }
            for n in plan.neurons
        ],
        "lobe_summaries_included": plan.lobe_summaries_included,
        "truncated_count": plan.truncated_count,
    }
    if plan.epistemic:
        out["epistemic"] = {
            "confidence": plan.epistemic.confidence,
            "graph_age_hours": plan.epistemic.graph_age_hours,
            "caveats": plan.epistemic.caveats,
            "recommendation": plan.epistemic.recommendation,
        }
    return json.dumps(out, indent=2)


def to_markdown(plan: ContextPlan) -> str:
    lines = [
        f"# Context Plan: {plan.task}",
        "",
        f"**Budget:** {plan.token_budget} tokens | "
        f"**Used:** {plan.tokens_used} tokens | "
        f"**Neurons:** {len(plan.neurons)} | "
        f"**Truncated:** {plan.truncated_count}",
        "",
    ]

    if plan.epistemic and plan.epistemic.caveats:
        for caveat in plan.epistemic.caveats:
            lines.append(f"> ⚠️ {caveat}")
        lines.append("")

    for n in plan.neurons:
        tier_icon = {
            "full_source": "📄",
            "signature_only": "✏️",
            "lobe_summary": "📦",
            "name_only": "🔖",
        }.get(n.inclusion_tier, "•")

        lines.append(f"## {tier_icon} `{n.name}` ({n.file}:{n.line_start})")
        lines.append(f"_Relevance: {n.relevance_score:.3f} | Tier: {n.inclusion_tier} | {n.tokens} tokens_")
        lines.append("")
        if n.inclusion_tier != "name_only":
            lang = "python" if n.file.endswith(".py") else ""
            lines.append(f"```{lang}")
            lines.append(n.content)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def to_claude_xml(plan: ContextPlan) -> str:
    """Format as Claude's <documents> XML for tool-use context injection."""
    parts = [f'<task>{_escape(plan.task)}</task>', "<documents>"]

    for i, n in enumerate(plan.neurons, 1):
        parts.append(f'  <document index="{i}">')
        parts.append(f"    <source>{n.file}:{n.line_start}::{n.name}</source>")
        parts.append(f"    <relevance>{n.relevance_score}</relevance>")
        parts.append(f"    <tier>{n.inclusion_tier}</tier>")
        parts.append("    <document_content>")
        parts.append(f"      {_escape(n.content)}")
        parts.append("    </document_content>")
        parts.append("  </document>")

    parts.append("</documents>")
    return "\n".join(parts)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
