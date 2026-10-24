# Insights

`cerebrofy insights` shows insights from the Insight Daemon, or forces a daemon run. Insights are stored as `type=insight` memories in `memories.db` and can be filtered by type, time window, and minimum confidence.

## What It Is

The Insight Daemon analyzes the codebase index and generates insights — trend alerts, silo risk notifications, coupling changes, and other observations worth bringing to a developer's attention. Insights are stored as memories and can be queried via CLI or MCP.

## CLI Reference

```bash
# Show existing insights
cerebrofy insights

# Filter by insight type
cerebrofy insights --type trend_alert
cerebrofy insights --type silo_risk

# Show insights from the last 7 days
cerebrofy insights --since 7d

# Force a daemon run before showing
cerebrofy insights --run

# Set minimum confidence
cerebrofy insights --min-confidence 0.8
```

- `--type` — filter by insight type (e.g., `trend_alert`, `silo_risk`)
- `--since` — time window, e.g. `7d`, `24h`
- `--run` — force a daemon run before showing insights
- `--watch` — stream insights as they generate (not implemented yet)
- `--min-confidence N` — minimum confidence 0-1 (default: 0.0)

## MCP Tool: `cerebrofy_insights`

**Input schema:**

```json
{
  "run_now": false,
  "type": "trend_alert",
  "since": "7d",
  "min_confidence": 0.7
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `run_now` | boolean | — | Force a daemon run before returning (default: `false`) |
| `type` | string | — | Filter by insight type (e.g., `trend_alert`, `silo_risk`) |
| `since` | string | — | Time window, e.g. `7d`, `24h` |
| `min_confidence` | number | — | Minimum confidence 0-1 (default: `0.7`) |

## Data Flow

Insights are stored as `type=insight` rows in `memories.db`. The daemon reads health snapshots, coupling metrics, and other index-derived signals to generate insight entries. Each insight has a type, title, body, confidence, affected neurons, affected lobes, and a recommendation.

## Integration Points

- **Memory** — insights are stored as `type=insight` memories in `memories.db`
- **Narrative** — new insights with confidence ≥ 0.9 trigger narrative regeneration
- **Health** — insight generation reads health snapshots for trend data

## Related

- [Memory](./memory.md) — where insights are persisted
- [Narrative](./narrative.md) — insights can trigger narrative updates
- [Health](./health.md) — health snapshots feed insight generation