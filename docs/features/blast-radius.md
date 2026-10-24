# Blast Radius

`cerebrofy blast-radius` computes the blast radius of a function or class — every caller at depth 1 and 2, test coverage gaps, lobe spread, and a risk score.

## What It Is

The blast radius tells you "if I change this function, what else breaks?" It runs BFS caller traversal over the live call graph, maps test coverage, and produces a risk score. This is the foundational analysis that powers several other features (impact, review, coverage-gap, upgrade).

## CLI Reference

```bash
cerebrofy blast-radius validate_token
cerebrofy blast-radius src/auth/tokens.py::validate_token --depth 3
cerebrofy blast-radius validate_token --format markdown   # PR comment format
```

- `target` — neuron id (`file::name`), `file:line`, or plain function name
- `--depth N` — BFS depth (default: 2, max: 5)
- `--format` — `markdown` (PR comment format) or default text

## MCP Tool: `cerebrofy_blast_radius`

**Input schema:**

```json
{
  "target": "src/auth/validator.py::validate_token",
  "depth": 2,
  "format": "json"
}
```

- `target` — accepts `"file::name"`, `"file:line"`, or a plain function name
- `depth` — defaults to 2 (max 5)
- `format` — `"json"` or `"markdown"` (PR comment format)

**Output:**

```json
{
  "target_neuron": { "name": "validate_token", "file": "src/auth/validator.py", "line": 42 },
  "callers": [
    { "name": "authenticate_request", "file": "src/api/middleware.py", "line": 18, "depth": 1 }
  ],
  "uncovered_callers": ["authenticate_request"],
  "risk_score": 0.72,
  "risk_label": "HIGH",
  "lobe_spread": 3,
  "summary": "..."
}
```

## Data Flow

1. Resolve the target neuron from the index
2. Run depth-N BFS upstream through `edges` (excluding `RUNTIME_BOUNDARY`)
3. For each caller, check test coverage (from `coverage.xml` or graph topology)
4. Compute lobe spread (number of distinct lobes callers belong to)
5. Compute risk score from caller count, depth, and coverage gaps

## Integration Points

- **`cerebrofy impact`** — uses blast radius as the core of pre-change impact prediction
- **`cerebrofy review`** — blast radius is one of the seven review checks
- **`cerebrofy coverage-gap`** — ranks uncovered neurons by blast radius × change velocity
- **`cerebrofy upgrade`** — effort estimation uses depth-2 blast radius per usage site
- **`cerebrofy arch`** — `max_blast_radius` rule kind checks blast radius against thresholds

## Related

- [Impact](../reference/cli.md#cerebrofy-impact) — pre-change impact prediction built on blast radius
- [Coverage Gap](./coverage-gap.md) — coverage gap predictor using blast radius × velocity
- [Architecture](../concepts/architecture.md) — `RUNTIME_BOUNDARY` edges excluded from BFS (Law II)