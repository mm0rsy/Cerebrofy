---
name: cerebrofy-governance
description: "Lobe ownership and review governance — dynamic CODEOWNERS, reviewer suggestions, and reporting-only blast-radius / bus-factor rules."
---

# Skill: cerebrofy-governance

> Lobe ownership and review governance — dynamic CODEOWNERS, reviewer
> suggestions, and reporting-only blast-radius / bus-factor rules.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to decide who owns a lobe.**

The Cerebrofy index already knows every neuron, lobe, and cross-lobe call edge.
Use `cerebrofy_governance` / `cerebrofy governance` and only open files the
command points at.

## When to use this skill

Invoke `/cerebrofy:governance` when you need to:

- generate or refresh a `CODEOWNERS` file that reflects git blame + call-graph
  topology instead of a stale hand-written list;
- decide who should review a PR (primary owner, cross-lobe co-reviewer, backup);
- check whether a change triggers `governance.rules` from
  `.cerebrofy/arch-rules.yaml` (high blast radius, silo lobe, missing tests);
- explain why a lobe is owned by a particular contributor.

## MCP tool

```
cerebrofy_governance(action="generate-codeowners", format="json")
cerebrofy_governance(action="suggest-reviewers", pr=142)
cerebrofy_governance(action="check-rules", pr=142, format="json")
cerebrofy_governance(action="check-rules", lobe="auth")
```

Error codes in the result:
- `[NO_INDEX]` — run `cerebrofy build` first.
- `[NO_GIT_HISTORY]` — the repository has no commits to compute blame from.
- `[GH_NOT_AUTHENTICATED]` — `pr` requires `gh auth login`.
- `[NO_GOVERNANCE_RULES]` — add a `governance.rules` block to
  `.cerebrofy/arch-rules.yaml`.

## CLI commands

```bash
cerebrofy governance generate-codeowners              # write ./CODEOWNERS
cerebrofy governance generate-codeowners --dry-run    # preview only
cerebrofy governance generate-codeowners --output .github/CODEOWNERS
cerebrofy governance sync                             # regenerate ./CODEOWNERS in place
cerebrofy governance suggest-reviewers --pr 142
cerebrofy governance suggest-reviewers --diff origin/main --format json
cerebrofy governance check-rules --lobe auth
cerebrofy governance check-rules --diff origin/main --format json
```

`generate-codeowners` never clobbers a hand-maintained file unless `--force` is
passed; generated files carry a header and are safe to regenerate.

`check-rules` is **reporting only** — it never blocks a merge and always exits 0
unless configuration is invalid.

## Ownership strategies

Configure in `.cerebrofy/config.yaml`:

```yaml
governance:
  strategy: git-blame        # git-blame | explicit | hybrid
  auto_sync_codeowners: false
  fallback_owner: "@tech-leads"
  activity_days: 90
```

- `git-blame` — author with the most blamed lines per lobe.
- `explicit` — owners from `.cerebrofy/team.yaml` (see below).
- `hybrid` — blame weighted by commits in the last `activity_days`.

Explicit ownership file:

```yaml
# .cerebrofy/team.yaml
default_owner: "@tech-leads"
lobes:
  auth:
    owners: ["alice@co.com", "@alice"]
  graph:
    owners: ["bob@co.com"]
```

## Governance rules

```yaml
# .cerebrofy/arch-rules.yaml
governance:
  rules:
    - name: high-blast-requires-two-reviews
      check:
        if_blast_radius: { gt: 30 }
        then_require_approvals: 2
    - name: silo-lobes-require-backup
      check:
        if_bus_factor: { eq: 1 }
        then_require_non_owner_review: true
    - name: new-neurons-require-coverage
      check:
        if_new_neurons: true
        then_require_test_file: true
```
