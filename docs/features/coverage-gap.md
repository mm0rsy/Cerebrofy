# Coverage Gap

`cerebrofy coverage-gap` ranks uncovered neurons by **blast radius × change velocity** to surface functions most likely to cause production bugs. A function that is widely-called, actively changing, and has no tests is the highest-priority coverage gap.

## What It Is

Coverage gap analysis helps you prioritize where to add tests. Instead of looking at raw coverage percentages, Cerebrofy combines blast radius (how many callers a function has) with change velocity (how often the file changes) to find the uncovered code that matters most.

## CLI Reference

```bash
cerebrofy coverage-gap                          # top 20 gaps, 30-day velocity window
cerebrofy coverage-gap --days 14               # tighten velocity to 2 weeks
cerebrofy coverage-gap --min-blast 2           # only functions with meaningful blast radius
cerebrofy coverage-gap --lobe auth             # restrict to a specific lobe
cerebrofy coverage-gap --risk critical         # show only CRITICAL gaps
cerebrofy coverage-gap --write-memories        # attach warning memories to HIGH/CRITICAL neurons
cerebrofy coverage-gap --output json           # machine-readable output
```

- `--days N` — velocity window in days (default: 30)
- `--min-blast N` — only functions with blast radius ≥ N
- `--lobe NAME` — restrict to a specific lobe
- `--risk LEVEL` — show only gaps at or above this risk level
- `--write-memories` — attach warning memories to HIGH/CRITICAL neurons
- `--output` — `json` for machine-readable output

## Output Fields

| Field | Meaning |
|-------|---------|
| **Gap score** | `risk_score(blast_radius) × velocity` — higher = more dangerous gap |
| **Callers** | Total callers at depth 1+2 from BFS traversal |
| **Commits/Nd** | Git commits touching the file in the last N days (velocity) |
| **Coverage source** | `coverage_xml` (pytest-cov) or `graph_topology` (call-edge fallback) |
| **Risk** | CRITICAL (≥100) / HIGH (≥25) / MEDIUM (≥5) / LOW (<5) |
| **Memories written** | Warning memories auto-attached to each HIGH/CRITICAL neuron (with `--write-memories`) |

## Coverage Sources

Coverage is sourced from `coverage.xml` (pytest-cov) when present; otherwise derived from the call graph (any test file with an edge to the neuron). The `coverage_source` field in every result tells you which was used.

## Data Flow

1. Identify all neurons without test coverage
2. Compute blast radius for each (callers at depth 1+2)
3. Compute change velocity from git history (commits per day)
4. Calculate gap score = risk_score(blast_radius) × velocity
5. Rank and filter by risk level, lobe, and min blast radius

## Integration Points

- **Memory** — `--write-memories` attaches warning memories to HIGH/CRITICAL gap neurons
- **Blast Radius** — caller counts come from depth-2 BFS traversal
- **Review** — coverage gap is one of the seven review checks

## Related

- [Blast Radius](./blast-radius.md) — caller traversal that feeds gap scoring
- [Memory](./memory.md) — warning memories for critical gaps
- [Review](./review.md) — coverage gap check in review