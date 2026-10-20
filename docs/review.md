# AI Review Copilot

`cerebrofy review` reviews a diff or GitHub pull request with the full Cerebrofy
graph, not just the changed lines. It combines blast radius, warning memories and
past decisions, architecture rules, test coverage gaps, missing caller updates,
cross-lobe coupling, and knowledge-silo ownership into one sorted report.

---

## Quick start

```bash
# Local pre-merge review
cerebrofy review --diff HEAD~1

# Review uncommitted changes
cerebrofy review --diff HEAD

# Dry-run a GitHub PR (nothing is posted)
cerebrofy review --pr 142

# Blocking findings only, machine-readable
cerebrofy review --pr 142 --severity error --format json

# Explicitly post inline comments plus a PR summary
cerebrofy review --pr 142 --post-comments
```

Posting is **opt-in**. Without `--post-comments` (CLI) or
`post_comments: true` (MCP), the report is printed locally and no `gh` command
is executed.

---

## Checks

| Check type | Source | What it reports |
|------------|--------|-----------------|
| `blast_radius` | `analysis/blast_radius.py` | Callers at depth 1 + 2, lobe spread, risk label |
| `memory_violation` | `memory/store.py` | Warning memories and past decisions attached to the neuron or lobe |
| `arch_rule` | `arch/rules.py` + `arch/checker.py` | Violations of `.cerebrofy/arch-rules.yaml`, filtered to changed files |
| `coverage_gap` | `analysis/coverage_gap.py` | Changed neurons with no `coverage.xml` or graph-topology coverage |
| `missing_caller_update` | `analysis/blast_radius.py` | Direct callers not updated in the same change |
| `coupling` | `health/metrics.py` semantics | Cross-lobe edges touching a changed neuron |
| `knowledge_silo` | `analysis/silo_detector.py` | Changed neurons owned by a single author; also drives suggested reviewers |

Optional integrations degrade gracefully. A missing or invalid
`arch-rules.yaml` and an unreadable `memories.db` are recorded under
`skipped_checks`; absent git blame data simply yields no silo findings, and a
missing `coverage.xml` falls back to graph-topology coverage.

---

## Severity score

Findings are sorted by `severity_score` descending:

```
severity_score = base_severity * (blast_factor + memory_factor + coverage_factor)

base_severity:   error = 3, warning = 2, info = 1
blast_factor:    1 + blast_radius / 50
memory_factor:   1.5 when a warning memory exists, otherwise 1.0
coverage_factor: 1.3 when the neuron has no test coverage, otherwise 1.0
```

`--severity error` keeps only errors; `--severity warning` keeps errors and
warnings; `--severity all` (default) keeps everything.

---

## Output

### Markdown (default)

The summary contains file/neuron counts, the maximum blast radius, severity
counts, a bullet per finding, suggested reviewers, the health impact
(`coupling` delta and average blast radius), and any skipped checks.

### JSON

```json
{
  "files_changed": 4,
  "neurons_changed": 7,
  "findings": [
    {
      "check_type": "blast_radius",
      "neuron": "validate_token",
      "file": "auth/tokens.py",
      "line": 42,
      "severity": "error",
      "message": "validate_token has 23 callers ...",
      "suggestion": "Review every caller before merging ...",
      "severity_score": 8.31
    }
  ],
  "suggested_reviewers": [
    {"email": "alice@co.com", "lobe": "auth", "reason": "sole author of validate_token"}
  ],
  "health_delta": {"coupling": 0.02, "avg_blast": 4.4},
  "summary": "🧠 Cerebrofy Review Summary ..."
}
```

---

## MCP tool

```json
{
  "diff": "main",
  "pr": 142,
  "severity": "all",
  "post_comments": false,
  "format": "markdown"
}
```

Supply `diff` or `pr` (`pr` takes precedence when both are present).
`post_comments` requires `pr` and an authenticated `gh` CLI.

### Error codes

| Code | Meaning |
|------|---------|
| `NO_INDEX` | `cerebrofy.db` not found — run `cerebrofy build` first |
| `NO_DIFF_PROVIDED` | Neither `diff` nor `pr` was supplied |
| `REF_NOT_FOUND` | The local git ref could not be diffed |
| `GH_NOT_AUTHENTICATED` | `pr` / `post_comments` requires `gh auth login` |

---

## GitHub posting

Cerebrofy delegates authentication entirely to `gh`; it never stores tokens.
When posting is enabled it creates one inline review comment per finding with a
line number, then one PR-level summary comment. Individual comment failures are
reported in `post_result.errors` without aborting the review.

The `gh` commands used are:

```bash
gh pr diff <N> --name-only
gh auth status
gh api repos/:owner/:repo/pulls/<N>/comments --method POST \
  --field body=... --field path=... --field line=... --field side=RIGHT
gh pr comment <N> --body <summary>
```
