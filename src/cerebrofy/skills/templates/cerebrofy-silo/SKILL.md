````markdown
# Skill: cerebrofy-silo

> Knowledge silo detection: git blame × call graph = bus factor risk per function.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use this skill

Invoke `/cerebrofy-silo` when you need to:
- Identify which functions are owned by a single contributor (bus factor = 1)
- Prioritise knowledge-transfer sessions before a team member leaves
- Find the riskiest silos before a major refactor
- Generate a C-level "key person dependency" report

## How to run

```bash
cerebrofy silo                        # top 20 silos across the whole codebase
cerebrofy silo --top 10               # top 10
cerebrofy silo --min-callers 3        # only high-traffic functions
cerebrofy silo --output json          # machine-readable output
```

Or via MCP tool:

```
cerebrofy_silo(min_callers=3, top=10)
```

## How to interpret results

The **silo score** = `caller_count ÷ unique_authors`.

| Score | Risk | Meaning |
|-------|------|---------|
| ≥ 20 | CRITICAL 🔴 | Many callers, single author — immediate bus factor risk |
| 8–20 | HIGH 🟠 | High-traffic code, very few authors — plan knowledge transfer |
| 3–8 | MEDIUM 🟡 | Moderate concentration — monitor on team changes |
| < 3 | LOW 🟢 | Well-distributed authorship |

A **silo** is any neuron with `unique_authors == 1` regardless of score.
The count of silos at the top of the report is the headline bus factor metric.

## Recommended follow-up actions

For each CRITICAL or HIGH silo:
1. Run `cerebrofy impact <neuron_name>` to see full blast radius
2. Prioritise a pair-programming or documentation session with the primary owner
3. Add a `cerebrofy memory add` warning attached to the neuron so future agents surface the risk automatically
````
