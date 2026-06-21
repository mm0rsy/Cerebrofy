# Skill: cerebrofy-context

> Graph-aware, budget-constrained optimal context window — the right code, nothing more.

## ⚠️ Navigation rule

**Call `cerebrofy_context` before starting any non-trivial coding task.**

This eliminates the need to glob-read files or guess what's relevant. The optimizer
returns exactly the neurons that fit within your token budget, ranked by relevance to
the task, with full source where it fits and signatures where it doesn't.

## When to use

- Before implementing a feature: get the relevant call graph pre-packed into your context.
- Before fixing a bug: seed the context with the affected neurons and their callers.
- When the context window is tight: use `--budget` to fit within model limits.
- Any time you want the minimum necessary code to understand a task.

## MCP tool

```
cerebrofy_context(task="add rate limiting to the login endpoint", budget=8000)
cerebrofy_context(task="fix the JWT refresh bug", budget=32000)
cerebrofy_context(task="refactor the embedder", format="claude-xml")
```

## CLI commands

```bash
cerebrofy context "add rate limiting to the login endpoint" --budget 8000
cerebrofy context "fix the JWT refresh bug" --budget 32000 --output json
cerebrofy context "refactor the embedder" --output claude-xml
```

## Inclusion tiers

The optimizer degrades gracefully as the budget fills:

| Tier | What's included | Cost |
|------|----------------|------|
| `full_source` | Complete function/class source | High |
| `signature_only` | Def line + docstring | Low |
| `lobe_summary` | Module-level markdown summary | Very low |
| `name_only` | `file:line::name` reference | Minimal |

## Output fields

| Field | Meaning |
|-------|---------|
| `neurons` | Packed neurons sorted by relevance score |
| `tokens_used` | Actual tokens consumed vs budget |
| `truncated_count` | Neurons that didn't fit in any tier |
| `lobe_summaries_included` | Module summaries used to fill remaining budget |
| `epistemic.graph_age_hours` | How stale the index is |
| `epistemic.caveats` | Warnings if index needs rebuilding |

## Scoring formula

```
relevance = semantic_score × 0.6 + graph_proximity × 0.4
```

KNN seeds get `graph_proximity = 1.0`, BFS neighbors get `0.5`.
