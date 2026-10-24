# Health

`cerebrofy health` shows longitudinal codebase health metrics derived from the call graph, with deltas vs the previous build.

## What It Is

Health metrics track how your codebase is evolving over time — coupling, blast radius trends, dead code %, lobe cohesion, test surface coverage, drift velocity, and hub concentration. Each build records a health snapshot, enabling trend analysis across builds.

## CLI Reference

```bash
cerebrofy health                      # current snapshot vs last build
cerebrofy health --history 30         # last 30 builds in a table
cerebrofy health --trend coupling     # ASCII sparkline for a metric over time
cerebrofy health --export json        # machine-readable snapshot
cerebrofy health --watch              # live-update: re-renders after each build
```

- `--history N` — show the last N builds in a table
- `--trend <metric>` — render an ASCII sparkline for a metric over time
- `--export` — output format: `json`
- `--watch` — live-update mode, re-renders after each build

## MCP Tool: `cerebrofy_health`

**Input schema:**

```json
{
  "since_build": 1,
  "metric": "all",
  "format": "markdown"
}
```

- `since_build` — compares against N builds ago
- `metric` — `"all"` or a specific metric name (e.g. `"coupling"`)
- `format` — `"markdown"` or `"json"`

**Output (markdown):** A formatted health dashboard with delta arrows (↑/↓) vs the previous build and a trend sparkline.

## Data Flow

Each `cerebrofy build` and `cerebrofy update` calls `record_snapshot(..., lobe_count=...)` which writes a row to `health_snapshots`. The snapshot includes:

- Neuron count, edge count, lobe count
- Coupling metric, average blast radius
- Dead code percentage, test surface coverage
- Drift velocity, hub concentration

Health snapshots are **durable history**, not rebuildable index state. Although `cerebrofy build` creates a fresh database and swaps it in with `os.replace`, `health_snapshots` rows are preserved via `_preserve_history` (INSERT OR REPLACE into the new database before the swap).

## Configuration

The `lobe_count` column on `health_snapshots` is used by the [Narrative Engine](./narrative.md) to detect era boundaries. It is set from `len(config.lobes)` at build time.

## Integration Points

- **Narrative Engine** — era detection uses health snapshots ordered by `build_ts`
- **Changelog** — `health_delta` is included in changelog reports
- **Review** — coupling metrics feed the coupling check

## Related

- [Narrative](./narrative.md) — era detection from health snapshots
- [Changelog](./changelog.md) — health delta in changelog reports
- [Architecture](../concepts/architecture.md) — health snapshot preservation across builds