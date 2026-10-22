# Cerebrofy Insights Prompt

You are an AI agent with access to the Cerebrofy Insight Daemon — a proactive analyzer that continuously reads across all stored data (graph, health, memories, sessions, arch rules) and surfaces insights without being asked.

## When to Use This Skill

- At the start of a session to understand current codebase health trends
- Before making architectural decisions to check for predicted violations
- When debugging recurring failures to see if patterns exist
- After completing a batch of work to see if the daemon detected anything

## Available Commands

```
/cerebrofy:insights                          # Show latest insights
/cerebrofy:insights --type trend_alert       # Filter by insight type
/cerebrofy:insights --since 7d              # Last 7 days
/cerebrofy:insights --run                   # Force daemon run now
```

## MCP Tool

```json
{
  "name": "cerebrofy_insights",
  "arguments": {
    "run_now": true,
    "type": "trend_alert",
    "since": "24h",
    "min_confidence": 0.7
  }
}
```

## Response Format

The tool returns structured JSON with:
- `insights`: array of insight objects (type, title, body, confidence, affected_neurons, affected_lobes, created_ts, recommendation)
- `total`: count of insights
- `last_daemon_run`: timestamp of last daemon execution

## Best Practices

1. **Run at session start** — Check for any critical insights before beginning work
2. **Filter by confidence** — Use `min_confidence: 0.8` for high-signal insights only
3. **Act on recommendations** — Each insight includes a concrete recommendation
4. **Run after major changes** — Force a daemon run after `cerebrofy build` or significant refactors

## Insight Types Reference

| Type | Trigger | Typical Action |
|---|---|---|
| trend_alert | Metric drifting 3+ builds | Review coupling/test surface changes |
| session_pattern | >50% failure in lobe | Add pre-commit checks for that lobe |
| silo_risk | Author inactive 60+ days | Knowledge sharing / documentation |
| arch_prediction | Blast radius → threshold | Enforce arch rules earlier |
| memory_conflict | Contradicting memories | Consolidate/supersede decisions |
| coverage_regression | Test surface ↓5%+ | Run coverage_gap, add tests |
| agent_drift | Changes > 2× predicted | Review session, run impact first |
| arch_violation_prediction | Pattern approaching violation | Refactor before merge |

---

*Auto-installed by Cerebrofy. Skill file: `cerebrofy-insights/SKILL.md`*