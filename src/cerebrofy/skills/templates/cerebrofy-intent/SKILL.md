---
name: cerebrofy-intent
description: Fetch team product intent — sprint goals, incidents, and architectural direction — from the Cerebrofy index before starting any task.
trigger: /cerebrofy:intent
---

# cerebrofy-intent

## Use When

- Starting any non-trivial coding task to understand team priorities and known risks
- Asking "what should I work on?", "what matters most right now?", or "are there known incidents affecting this area?"
- Before modifying code in lobes that may be sprint-critical or incident-affected
- When architectural guidance is needed to ensure changes align with team direction

## ⚠️ Navigation Rule

Always call `cerebrofy_intent` **before** calling `search_code` or `get_neuron` for task-oriented work. Intent shapes relevance — a function in a sprint-priority lobe deserves more care than one in a deprioritized lobe.

## How to Use

### MCP Tool Call (AI agents)

```
Use cerebrofy_intent with arguments: {}
```

For lobe-specific relevance:
```
Use cerebrofy_intent with arguments: {"lobe": "auth"}
```

For neuron-specific relevance:
```
Use cerebrofy_intent with arguments: {"neuron": "auth/tokens.py::validate_token"}
```

### CLI

```bash
cerebrofy intent show              # human-readable summary
cerebrofy intent show --json       # machine-readable JSON
cerebrofy intent validate          # check YAML against known lobes
cerebrofy intent init              # scaffold intent.yaml
cerebrofy intent edit              # open in $EDITOR
```

## Output Shape (JSON)

```json
{
  "sprint": {
    "name": "Payments v2",
    "goal": "Ship Stripe subscription billing",
    "deadline": "2026-07-15",
    "priority_lobes": ["payments", "api"],
    "deprioritized_lobes": ["viz"]
  },
  "incidents": [...],
  "architecture": {
    "direction": "Event-driven via Kafka",
    "avoid_patterns": ["direct DB calls from API layer"],
    "principles": ["All payment flows must be idempotent"]
  },
  "team_context": {
    "concerns": ["payments/ test coverage is 34%"],
    "upcoming_risks": ["Stripe API v4 migration by 2026-09-01"]
  },
  "relevance_to_query": null
}
```

When `lobe` or `neuron` is passed, `relevance_to_query` contains:
- `sprint_relevance`: HIGH / MEDIUM / LOW with reason
- `active_incidents`: list of open/non-patched incidents for affected lobes
- `architectural_guidance`: AVOID and PRINCIPLE lines
- `priority`: matching team concern

## Error Codes

| Code | Meaning |
|------|---------|
| `NO_INTENT_FILE` | `.cerebrofy/intent.yaml` not found — create it with `cerebrofy intent init` |
| `INVALID_INTENT_YAML` | YAML is malformed — fix syntax and re-run |

## Notes

- `intent.yaml` is **committed to the repo** — it is team-shared, not per-developer
- If no intent.yaml exists, all MCP tools still function; `intent_context` field is omitted
- All other Cerebrofy tool responses include a compact `intent_context` field automatically when intent.yaml exists
