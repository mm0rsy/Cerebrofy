# Skill: cerebrofy-upgrade

> Map every place your code uses a dependency's changing API, estimate the migration effort, and sequence the fix — before you bump the version.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it via MCP tools first.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use

- Before upgrading a major dependency (pydantic v1 → v2, requests 2 → 3, …)
- When Renovate/Dependabot opens a major-version PR
- To estimate migration effort and risk for sprint planning
- After upgrading, to prove no old API patterns remain (`validate=true`)
- Before a release, to prioritise the highest-blast call sites first

## How to use via MCP

```
cerebrofy_upgrade(package="pydantic", from_version="1.10", to_version="2.0")
cerebrofy_upgrade(package="pydantic", breaking_only=true)
cerebrofy_upgrade(package="pydantic", auto_fix=true, step=[1, 2])
cerebrofy_upgrade(package="pydantic", validate=true)
```

The tool returns:
- `breaking_changes` — each old → new API, severity, affected neuron ids, effort score
- `steps` — ordered migration steps with `neurons_to_update` and `loc_estimate`
- `total_effort_hours`, `risk` (`LOW` / `MEDIUM` / `HIGH`)
- `auto_fix_results` — per-step fixed-neuron counts and errors (when `auto_fix=true`)
- `validation` — pass/fail + remaining `file:line` sites (when `validate=true`)

## How to use via CLI

```bash
cerebrofy upgrade pydantic --from v1 --to v2
cerebrofy upgrade requests --breaking-only
cerebrofy upgrade pydantic --manifest ./pydantic.yaml
cerebrofy upgrade pydantic --diff ./library-api-diff.json
cerebrofy upgrade pydantic --auto-fix --step 1,2
cerebrofy upgrade pydantic --validate
cerebrofy upgrade pydantic --format json
```

## Decision guide

| Signal | Meaning |
|--------|---------|
| `total_effort_hours` ≥ 8 or `risk: HIGH` | Schedule as a dedicated migration, not a drive-by bump |
| High `max_blast_radius` on a step | Update that neuron early; callers/tests are more likely to break |
| `class Config` / structural changes | Manual rewrite; the fixer deliberately refuses to guess |
| `auto_fix_results[].errors` | Manual review required for that file — do not ignore |
| `validate` FAIL | Do not merge the version bump yet; fix the listed `file:line` sites |

## Safety rules

- Auto-fix is opt-in and only rewrites Python files whose transformed AST re-parses.
- Never auto-fix a whole repo during a review; run the plan first, inspect the steps,
  then apply only the steps you selected.
- Manifests are curated, not exhaustive. Always cross-check the library's migration guide.
- All planning is offline: no PyPI/GitHub network calls.

## Error codes

| Code | Action |
|------|--------|
| `NO_INDEX` | Run `cerebrofy build` first |
| `PACKAGE_NOT_USED` | Package is not imported (or has no affected API usage) — verify the package/version |
| `MANIFEST_NOT_FOUND` | No curated manifest — pass `--manifest` / `--diff` |
| `VERSION_NOT_FOUND` | The manifest does not cover this version pair — pass a custom diff |
