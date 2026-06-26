````markdown
# Skill: cerebrofy-coverage-gap

> Test coverage gap predictor: rank uncovered neurons by blast radius × velocity to find the functions most likely to cause production bugs.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use this skill

Invoke `/cerebrofy-coverage-gap` when you need to:
- Prioritise which untested functions to cover before a release
- Find the highest-risk blind spots after adding new features
- Answer "what untested code is most likely to break in production?"
- Drive a focused testing sprint with objective risk ranking

## How to run

```bash
cerebrofy coverage-gap                        # top 20 gaps across the whole codebase
cerebrofy coverage-gap --top 10               # top 10
cerebrofy coverage-gap --days 14              # tighten velocity window to 2 weeks
cerebrofy coverage-gap --min-blast 2          # only functions with meaningful blast radius
cerebrofy coverage-gap --lobe auth            # restrict to a specific lobe
cerebrofy coverage-gap --risk critical        # only CRITICAL gaps
cerebrofy coverage-gap --write-memories       # attach warning memories to HIGH/CRITICAL neurons
cerebrofy coverage-gap --output json          # machine-readable output
```

Or via MCP tool:

```
cerebrofy_coverage_gap(days=30, top=10, min_blast=2)
```

## Coverage source

The tool automatically selects the best available coverage signal:

1. **`coverage.xml`** (preferred) — if pytest-cov has been run (`pytest --cov`), the XML report at the repo root is parsed for line-level hit counts. This is the most accurate signal.
2. **Graph topology** (fallback) — if no `coverage.xml` is present, a neuron is considered covered if any function in `tests/` has a call edge to it in the index.

The `coverage_source` field in every result tells you which source was used.

## How to interpret results

The **gap score** = `risk_score(blast_radius) × velocity`.

- **blast_radius** — weighted caller count: direct callers + 0.4 × indirect callers, normalised by lobe coupling
- **velocity** — git commits touching the file in the last N days (default: 30)

| Score | Risk | Meaning |
|-------|------|---------|
| ≥ 100 | CRITICAL 🔴 | Widely-called, actively changing, zero tests — highest production risk |
| 25–100 | HIGH 🟠 | Significant exposure; should be covered before next release |
| 5–25 | MEDIUM 🟡 | Moderate risk; schedule for coverage in coming sprint |
| < 5 | LOW 🟢 | Low traffic or dormant; address when convenient |

A gap score of **0** means the function has not been touched in the velocity window — it is stale but not actively risky.

## Recommended follow-up actions

For each CRITICAL or HIGH gap:
1. Run `cerebrofy blast-radius <neuron_name>` to see the full caller tree and understand blast radius in detail
2. Run `cerebrofy impact <neuron_name>` to get a recommended test-writing sequence
3. Write a test targeting the function directly, then re-run `cerebrofy coverage-gap` to confirm it clears
4. Use `--write-memories` to attach a warning memory so future AI sessions surface the risk automatically
````
