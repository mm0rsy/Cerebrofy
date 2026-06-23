# Skill: cerebrofy-impact

> Run a pre-change impact prediction before touching any function or class.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it via MCP tools first.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use

- Before any refactor, rename, or signature change
- When asked "what breaks if I change X?"
- Before an AI agent starts editing a function — run this first to know the blast radius
- When estimating the effort of a change (check `complexity_rating` and `estimated_loc`)

## How to use via MCP

```
cerebrofy_impact(target="auth/tokens.py::validate_token")
cerebrofy_impact(target="validate_token", depth=3)
cerebrofy_impact(target="auth/tokens.py:42", show_tests=true)
```

The tool returns:
- `target` — the resolved neuron (name, file, line, lobe)
- `callers_depth1` / `callers_depth2` — direct and transitive callers
- `lobe_spread` — how many architectural boundaries the change crosses
- `estimated_loc` — lines of code across all affected neurons
- `complexity_rating` — LOW / MEDIUM / HIGH
- `runtime_boundary_callers` — callers across process/framework boundaries (manual check required)
- `covering_tests` — test functions that reach the target
- `uncovered_callers` — callers with no detected test coverage
- `memory_warnings` — warning memories attached to this neuron (from `cerebrofy memory`)
- `refactoring_sequence` — recommended order to update callers to minimise breakage

## How to use via CLI

```bash
cerebrofy impact auth/tokens.py::validate_token
cerebrofy impact validate_token --depth 3
cerebrofy impact auth/tokens.py::validate_token --output json
cerebrofy impact auth/tokens.py::validate_token --no-sequence
```

## Decision guide

| `complexity_rating` | Recommended action |
|---------------------|--------------------|
| LOW | Proceed — change is contained |
| MEDIUM | Review callers list before editing |
| HIGH | Full impact report review + update tests before touching the target |

## Quick reference

| Goal | MCP call |
|------|---------|
| Pre-flight check before refactor | `cerebrofy_impact(target="file::name")` |
| Deeper traversal | `cerebrofy_impact(target="...", depth=3)` |
| Skip test mapping (faster) | `cerebrofy_impact(target="...", show_tests=false)` |
| Check memory warnings only | read `memory_warnings` field from any call |
