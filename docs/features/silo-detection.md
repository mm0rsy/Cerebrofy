# Silo Detection

`cerebrofy silo` identifies knowledge silos — functions with high blast radius owned by few contributors. It overlays `git blame` authorship on the call graph to compute bus factor risk: a function called by many but written by one is a single point of failure.

## What It Is

Silo detection helps you answer "if this person left, what breaks?" By combining call graph data with git blame, Cerebrofy identifies neurons that are widely depended upon but owned by a single contributor — these are your highest bus-factor risks.

## CLI Reference

```bash
cerebrofy silo                              # full report, top 20 silos
cerebrofy silo --top 10 --min-callers 3    # high-traffic functions only
cerebrofy silo --lobe auth                 # restrict to a specific lobe
cerebrofy silo --author alice@company.com  # "if Alice left, what breaks?"
cerebrofy silo --risk high                 # show only HIGH/CRITICAL silos
cerebrofy silo --write-memories            # attach warning memories to HIGH/CRITICAL neurons
cerebrofy silo --output json               # machine-readable output
```

- `--top N` — limit to top N silos (default: 20)
- `--min-callers N` — only show functions with at least N callers
- `--lobe NAME` — restrict to a specific lobe
- `--author EMAIL` — show silos owned by a specific author ("if this person left, what breaks?")
- `--risk LEVEL` — show only silos at or above this risk level (CRITICAL, HIGH, MEDIUM, LOW)
- `--write-memories` — attach warning memories to HIGH/CRITICAL neurons
- `--output` — `json` for machine-readable output

## Output Fields

| Field | Meaning |
|-------|---------|
| **Silo score** | `caller_count ÷ unique_authors` — higher = more dangerous concentration |
| **Primary owner** | Author with the most lines in the neuron's line range |
| **Own%** | Fraction of lines owned by the primary author |
| **Unique authors** | Number of distinct contributors to this neuron |
| **Risk** | CRITICAL (≥20) / HIGH (≥8) / MEDIUM (≥3) / LOW (<3) |
| **Memories written** | Warning memories auto-attached to each HIGH/CRITICAL neuron (with `--write-memories`) |

## Data Flow

1. Query all neurons from the index with their caller counts (depth-1 BFS)
2. Run `git blame` on each neuron's file to determine line ownership
3. Compute silo score = caller_count ÷ unique_authors
4. Assign risk level based on score thresholds
5. Optionally write warning memories to `memories.db` for HIGH/CRITICAL neurons

## Integration Points

- **Memory** — `--write-memories` attaches warning memories to silo neurons
- **Governance** — bus factor feeds CODEOWNERS generation and reviewer suggestions
- **Review** — knowledge silo is one of the seven review checks

## Related

- [Governance](./governance.md) — bus factor and ownership strategies
- [Review](./review.md) — knowledge silo check in review
- [Memory](./memory.md) -- warning memories written for silo neurons