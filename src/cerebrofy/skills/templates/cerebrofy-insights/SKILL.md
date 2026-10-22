---
name: cerebrofy-insights
description: Query or run the Cerebrofy Insight Daemon to surface proactive codebase insights.
author: cerebrofy
version: 1.0.0
---

# Cerebrofy Insights Skill

This skill provides access to the Cerebrofy Insight Daemon — a background reasoning process that continuously analyzes your codebase data (graph, health, memories, sessions, arch rules) and surfaces proactive insights without being asked.

## Commands

| Slash Command | MCP Tool | Description |
|---|---|---|
| `/cerebrofy:insights` | `cerebrofy_insights` | Show latest insights |
| `/cerebrofy:insights --type trend_alert` | `cerebrofy_insights` with `{"type": "trend_alert"}` | Filter by insight type |
| `/cerebrofy:insights --since 7d` | `cerebrofy_insights` with `{"since": "7d"}` | Show insights from last 7 days |
| `/cerebrofy:insights --run` | `cerebrofy_insights` with `{"run_now": true}` | Force daemon run and show results |

## Insight Types

- **trend_alert** — Health metric drifting 3+ consecutive builds
- **session_pattern** — Session failure rate > 50% for a lobe
- **silo_risk** — Primary author inactive > 60 days on high-blast lobe
- **arch_prediction** — Blast radius trending toward rule threshold
- **memory_conflict** — Two memories with contradicting bodies on same neuron
- **coverage_regression** — Test surface dropped > 5% in one sprint
- **agent_drift** — Agent changed more neurons than impact predicted
- **arch_violation_prediction** — New edge pattern approaching rule violation

## Usage Examples

```
/cerebrofy:insights
/cerebrofy:insights --type trend_alert
/cerebrofy:insights --run --since 24h
```

## Agent Invocation

When an AI agent needs this feature without a human typing the slash command, it calls the MCP tool directly:

```
Use cerebrofy_insights with arguments: {"run_now": true}
Use cerebrofy_insights with arguments: {"type": "trend_alert", "min_confidence": 0.8}
```

## Hooks

The daemon runs automatically after:
- `cerebrofy build` completion
- `cerebrofy update` completion
- Scheduled cron (default: hourly, configured via `cerebrofy init`)

## Configuration

No additional configuration required. Uses existing `.cerebrofy/config.yaml` and database.