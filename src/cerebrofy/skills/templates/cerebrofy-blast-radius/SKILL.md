# Skill: cerebrofy-blast-radius

> Graph-topology risk report for any code change — every caller affected, test coverage gaps, and a risk score.

## ⚠️ Navigation rule

**Do NOT open or glob-read source files to understand what a change affects.**

This repo has a pre-built Cerebrofy index. Use `cerebrofy_blast_radius` to compute the
full caller graph before reading or editing anything.

## When to use

- Before reviewing a PR: run blast radius on every changed function to understand the real scope.
- Before making a change: know who calls the function you're about to modify.
- After a diff: validate that the actual impact matches the predicted scope.
- Any time you need to answer "what breaks if I change X?"

## MCP tool

```
cerebrofy_blast_radius(target="auth/tokens.py::validate_token", depth=2)
cerebrofy_blast_radius(target="validate_token")
cerebrofy_blast_radius(target="auth/tokens.py:42")
```

## CLI commands

```bash
cerebrofy blast-radius --base main --head HEAD        # full PR diff
cerebrofy blast-radius --pr 142                       # fetch diff via gh CLI
cerebrofy blast-radius auth/tokens.py::validate_token # single neuron
cerebrofy blast-radius --base main --output markdown  # GitHub-ready comment
cerebrofy blast-radius --pr 142 --post-comment        # post comment to PR
```

## Output fields

| Field | Meaning |
|-------|---------|
| `callers_depth1` | Functions that call the target directly |
| `callers_depth2` | Functions that call the callers |
| `covering_tests` | Test neurons that reach the target via the call graph |
| `uncovered_callers` | Callers with no test reaching them — highest regression risk |
| `risk_label` | `LOW` / `MEDIUM` / `HIGH` based on caller count and lobe spread |
| `lobe_spread` | Number of distinct modules in the caller set |

## Risk scoring

```
risk = (direct_callers × 1.0 + indirect_callers × 0.4)
     × (lobes_calling / total_lobes)
     / max(test_coverage_ratio, 0.05)
```

Score ≥ 10 → HIGH · Score ≥ 3 → MEDIUM · Score < 3 → LOW

## Workflow

1. Call `cerebrofy_blast_radius` with the changed neuron's identifier.
2. Read `risk_label` — HIGH means callers span multiple lobes with low test coverage.
3. Check `uncovered_callers` — these are the regression landmines.
4. Use `get_neuron` on any specific caller to read its implementation before editing.
5. After changes, run `cerebrofy validate` to confirm index is still in sync.
