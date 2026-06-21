# Skill: cerebrofy-epistemic

> Know how much to trust Cerebrofy's answers before acting on them.

## ⚠️ Navigation rule

**Call `cerebrofy_epistemic` before any significant refactor or architectural decision.**

Every other Cerebrofy tool response automatically includes an `"epistemic"` field.
Use this dedicated command when you want the full confidence breakdown up front.

## When to use

- Before a large refactor: check that the index is fresh enough to trust blast radius and impact predictions.
- When the index feels stale: get an explicit confidence score before acting.
- When onboarding to a repo: understand what languages are not indexed.
- Any time a tool response shows `confidence < 0.7`.

## MCP tool

```
cerebrofy_epistemic()
cerebrofy_epistemic(format="human")
```

## CLI commands

```bash
cerebrofy epistemic            # human-readable confidence report
cerebrofy epistemic --json     # machine-readable JSON for agent pipelines
```

## Confidence formula

```
confidence = age_factor × change_factor × language_factor × dispatch_factor

age_factor      = max(0.5, 1.0 - graph_age_hours / 168)   # decays over 1 week
change_factor   = max(0.5, 1.0 - neurons_changed / total)
language_factor = max(0.5, 1.0 - 0.1 × unindexed_count)
dispatch_factor = 0.9 if dynamic dispatch detected, else 1.0
```

## Confidence thresholds

| Score | Meaning |
|-------|---------|
| ≥ 0.7 ✅ | Index is reliable — proceed |
| 0.5–0.7 ⚠️ | LOW CONFIDENCE — results may be incomplete |
| < 0.5 🔴 | STALE DATA — rebuild before acting |

## Epistemic field in every tool response

All data-reading MCP tools (search_code, get_neuron, blast_radius, context, health, list_lobes)
automatically include an `"epistemic"` field:

```json
{
  "results": [...],
  "epistemic": {
    "overall_confidence": 0.84,
    "graph_age_hours": 2.1,
    "neurons_changed_since_build": 0,
    "caveats": [],
    "recommendation": "Index is fresh — results are reliable"
  }
}
```
