---
name: cerebrofy-review
description: "Graph-aware code review covering blast radius, past decisions, architecture rules, test coverage gaps, and knowledge silos."
---

# Skill: cerebrofy-review

> Graph-aware code review — blast radius, past decisions, architecture rules, test coverage gaps, and knowledge silos in one report.

## ⚠️ Navigation rule

**Do NOT open or glob-read source files to review a change.**

This repo has a pre-built Cerebrofy index. Use `cerebrofy_review` to review the diff
with the call graph, recorded decisions, and architecture rules already loaded.

## When to use

- Before opening a PR: self-review the diff with full graph context.
- Before merging someone else's PR: find unchecked callers, memory violations, and coverage gaps.
- Before a refactor: confirm the blast radius and missing caller updates.
- When asked "what will this change break?" or "who should review this?".

## MCP tool

```
cerebrofy_review(diff="HEAD~1", severity="all", format="markdown")
cerebrofy_review(diff="main", severity="warning")
cerebrofy_review(pr=142, format="json")
cerebrofy_review(pr=142, post_comments=true, severity="error")
```

The default is a local dry-run. Comments are posted only when `post_comments` is
explicitly `true` and the `gh` CLI is authenticated.

## CLI commands

```bash
cerebrofy review --diff HEAD~1                 # local pre-merge review
cerebrofy review --diff HEAD                   # uncommitted changes
cerebrofy review --pr 142                      # dry-run PR review
cerebrofy review --pr 142 --severity error     # only blocking findings
cerebrofy review --pr 142 --post-comments      # post inline + summary comments
cerebrofy review --diff main --format json     # machine-readable output
```

## Checks

| Check type | What it means |
|------------|---------------|
| `blast_radius` | The changed neuron has many callers and/or lobe spread |
| `memory_violation` | A recorded warning or past decision applies here |
| `arch_rule` | A rule in `.cerebrofy/arch-rules.yaml` is violated |
| `coverage_gap` | No test reaches the changed neuron |
| `missing_caller_update` | Direct callers are not updated in this change |
| `coupling` | The change adds cross-lobe coupling |
| `knowledge_silo` | Few authors own this widely-called code |

Findings are sorted by `severity_score` (descending):

```
severity_score = base_severity * (blast_factor + memory_factor + coverage_factor)
base_severity: error=3, warning=2, info=1
blast_factor: 1 + blast_radius / 50
memory_factor: 1.5 when a warning memory exists
coverage_factor: 1.3 when the neuron has no test coverage
```

## Workflow

1. Call `cerebrofy_review` with the diff or PR.
2. Read the highest `severity_score` findings first; they combine impact, memory, and coverage.
3. Check `suggested_reviewers` when a knowledge silo is flagged.
4. Use `get_neuron` or `cerebrofy_impact` on any flagged neuron before editing.
5. Re-run `cerebrofy_review` after the fix.
6. Never post comments unless the user explicitly asks for `--post-comments`.
