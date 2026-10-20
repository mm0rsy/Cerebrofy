````markdown
# Skill: cerebrofy-plan

> Natural-language refactor planning: describe the change in plain English, review a graph-aware migration plan before a single line is touched.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use this skill

Invoke `/cerebrofy:plan` when you need to:
- Plan an extraction ("extract the payment logic into a payments service")
- Plan a move ("move all database connection code into a db/ module")
- Produce a safe, ordered migration checklist before any AI agent starts editing
- Generate a machine-readable refactoring task list for CI/CD (`--output json`)

## How to run

```bash
cerebrofy plan "extract the payment logic into a payments service"
cerebrofy plan "move all database connection code into a db/ module"
cerebrofy plan "extract the auth helpers" --output json   # CI/CD task list
cerebrofy plan "extract the auth helpers" --execute       # + execution handoff
```

Or via MCP tool:

```
cerebrofy_plan(description="extract the payment logic into a payments service", dry_run=true)
```

The planner only reads the index — it never modifies files. `dry_run` defaults to
true; setting it to false only prepares an execution-handoff context window for
the agent that will implement the plan.

## How to read the plan

1. **What Cerebrofy Found** — KNN seeds matched by the description, plus graph
   expansions (>50% internal edges) that belong to the same cohesive unit.
2. **Proposed Structure** — the new module and the file each source file maps to.
3. **Callers to Update** — every direct caller outside the cluster (100% list).
4. **Step-by-Step Migration Plan** — skeleton first, callees before callers,
   re-export stubs before caller updates, stub removal last. `callers break`
   flags steps that can break callers (e.g. RUNTIME_BOUNDARY callers).
5. **Estimated effort / Files affected / Blast radius** — aggregate graph metrics.

## Error codes

| Code | Meaning | Fix |
|------|---------|-----|
| `NO_INDEX` | cerebrofy.db not found | run `cerebrofy build` first |
| `CLUSTER_TOO_SMALL` | fewer than 2 neurons matched | refine the description |
| `CLUSTER_TOO_LARGE` | more than 200 neurons matched | scope the description more narrowly |

## Recommended follow-up actions

1. Review the plan with the developer (human-in-the-loop) before executing.
2. Execute step by step, running `cerebrofy_impact <neuron>` before each move to
   verify the blast radius stays contained.
3. After execution, run `cerebrofy validate` and the test suite, then
   `cerebrofy remember` a decision memory describing what moved and why.
````
