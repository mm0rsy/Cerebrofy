# `cerebrofy review` — AI Review Copilot

Graph-aware review of a local diff or GitHub PR. Runs seven checks against the live index, scores findings by severity, and optionally posts comments via `gh`.

## What It Is

`cerebrofy review` combines blast radius, warning memories and past decisions, architecture rules, test coverage gaps, missing caller updates, cross-lobe coupling, and knowledge-silo ownership into one severity-sorted report, plus suggested reviewers and a PR-ready summary.

## Quick Start

```bash
# Index your repo
cerebrofy init
cerebrofy build

# Review a local diff (no GitHub auth needed)
cerebrofy review --diff HEAD~1 --format markdown

# Review a GitHub PR (requires `gh auth login`)
cerebrofy review --pr 42 --severity high --post-comments --format markdown
```

## CLI Reference

```bash
cerebrofy review [OPTIONS]

Options:
  --pr INTEGER              GitHub PR number (requires authenticated `gh` CLI).
  --diff TEXT               Local git ref to diff against (e.g. HEAD~1, main..feature).
  --severity [low|medium|high|critical]
                            Minimum severity to include in output.
  --post-comments           Post findings as PR comments (opt-in, requires `--pr`).
  --format [markdown|json]  Output format.
  -h, --help                Show this message and exit.
```

**Rules:**
- Exactly one of `--pr` or `--diff` is required.
- `--post-comments` requires `--pr`.
- Default format is `markdown`; `--format json` emits machine-readable payloads.

## The Seven Checks

| Check | What it does | Skipped when |
|-------|-------------|--------------|
| `blast_radius` | Finds all callers (transitive) of changed neurons; ranks by blast radius × change velocity. | No changed neurons with callers. |
| `memory_violation` | Matches changed neurons against warning/decision memories in the same lobe (and lobe-wide decisions mentioning the neuron). | No memories or no matching lobe. |
| `arch_rule` | Evaluates `.cerebrofy/arch-rules.yaml` against the call graph; reports violations with confidence. | No arch rules or no rules matching changed lobes. |
| `coverage_gap` | Ranks uncovered neurons by blast radius × change velocity; uses `coverage.xml` if present, falls back to graph topology. | No coverage data and graph fallback disabled. |
| `missing_caller_update` | Detects callers that were *not* updated when their callee changed signature/behavior (renames, param changes, deletions). | No signature/behavior changes detected. |
| `coupling` | Cross-lobe coupling metrics: fan-in/fan-out, shared callers, instability. | Single-lobe change or no cross-lobe edges. |
| `knowledge_silo` | Bus-factor risk: which neurons/owners would be critical losses. Uses git blame + graph topology. | Single contributor or no ownership data. |

Each check emits `findings` (if any) and a `skipped_reason` if it couldn't run. The output includes a summary table and the list of `skipped_checks`.

## Severity Model

Findings are scored `low` / `medium` / `high` / `critical`:

- `critical` — blast radius ≥ 50 callers **or** critical memory violation **or** arch rule FAIL with `confidence ≥ 0.9`.
- `high` — blast radius 10–49 **or** arch rule FAIL/WARN **or** missing caller update on public API.
- `medium` — blast radius 3–9 **or** coverage gap in hot path **or** coupling > 0.7.
- `low` — everything else (informational).

Within each severity, findings are ordered by blast radius (descending), then file path.

## Output

### Markdown (default)

```
## Review Summary
- Blast radius: 23 findings (3 high, 8 medium, 12 low)
- Memory violations: 0
- Architecture rules: 1 WARN
- Coverage gaps: 4 high, 2 medium
- Missing caller updates: 1
- Coupling: 2 lobes cross-coupled
- Knowledge silos: 1 critical (bus factor = 1)

Skipped checks: []
```

### JSON

```json
{
  "checks": [
    {
      "name": "blast_radius",
      "findings": [...],
      "skipped_reason": null
    }
  ],
  "summary": {
    "critical": 0,
    "high": 3,
    "medium": 8,
    "low": 12
  },
  "skipped_checks": []
}
```

## MCP Tool: `cerebrofy_review`

**Input schema:**

```json
{
  "diff": "HEAD~1",
  "pr": 142,
  "severity": "all",
  "post_comments": false,
  "format": "markdown"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `diff` | string | — | Git ref to diff against (e.g. `HEAD~1`, `main`) |
| `pr` | integer | — | GitHub PR number to review (requires `gh` auth) |
| `severity` | string | — | Minimum severity: `error`, `warning`, or `all` (default: `all`) |
| `post_comments` | boolean | — | Post findings as inline PR comments plus a summary (requires `pr` and `gh` auth; default: false — local dry-run) |
| `format` | string | — | `markdown` (default) or `json` |

**Output:** findings sorted by `severity_score` descending, with `skipped_checks` for degraded integrations, `suggested_reviewers`, health delta, and a PR-ready markdown summary (or the full report object in JSON).

Error codes: `[NO_INDEX]` when no index exists; `[NO_DIFF_PROVIDED]` when neither `diff` nor `pr` is supplied; `[GH_NOT_AUTHENTICATED]` when `gh` is unavailable or unauthenticated.

Posting is **opt-in** (`post_comments: true` + `pr: 42`). No `gh` API calls are made otherwise.

## Configuration

Optional config keys (`.cerebrofy/config.yaml`):

```yaml
governance:
  auto_sync_codeowners: false   # also used by review for CODEOWNERS hints
arch:
  enabled: true
memory:
  enabled: true
```

All checks degrade gracefully if their data source is unavailable — they emit `skipped` with a reason, never a false "clean" result.

## Error Codes Reference

| Code | Meaning |
|------|---------|
| `NO_INDEX` | `.cerebrofy/db/cerebrofy.db` missing; run `cerebrofy build`. |
| `NO_DIFF_PROVIDED` | Missing `--pr` or `--diff` (or `--post-comments` without `--pr`). |
| `GH_NOT_AUTHENTICATED` | `gh` CLI not installed, not authenticated, or PR unavailable. |
| `REF_NOT_FOUND` | `--diff` ref does not exist. |

## Safety

- Read-only index access (SQLite `mode=ro`).
- No `gh` API calls unless `--post-comments` / `post_comments: true`.
- No shell injection: `gh` args are passed via `subprocess.run` with an explicit argv list; no string interpolation.
- Generated memories/links are opt-in (`--write-memories` on `arch check`, `review` does not write).

## Examples

### Local diff review (offline)

```bash
cerebrofy review --diff HEAD~1 --severity medium --format json
```

### GitHub PR review with posting

```bash
gh auth login  # once
cerebrofy review --pr 42 --post-comments --severity high
```

### CI integration

```yaml
# .github/workflows/review.yml
- name: AI review
  run: cerebrofy review --pr ${{ github.event.pull_request.number }} --post-comments --format json
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `NO_INDEX` | DB missing or wrong repo root | `cerebrofy build` from repo root |
| `GH_NOT_AUTHENTICATED` | `gh` not logged in | `gh auth login` |
| `NO_DIFF_PROVIDED` | Forgot `--pr` with `--post-comments` | Add `--pr <number>` |
| Empty output | No findings or all below `--severity` | Lower `--severity` or check `skipped_checks` |
| Slow on large diff | Blast radius walks many callers | Narrow `--diff` scope or raise `--severity` |

## Related

- [Governance](./governance.md) — CODEOWNERS, reviewer suggestions, governance rules.
- [Upgrade](./upgrade.md) — dependency upgrade navigator.
- [Blast Radius](./blast-radius.md) — caller traversal that feeds review findings.
- [Coverage Gap](./coverage-gap.md) — coverage gap check in review.
- [Silo Detection](./silo-detection.md) — knowledge silo check in review.
- [Architecture](../concepts/architecture.md) — data flow and module map.
- [Configuration](../getting-started/configuration.md) — config schema.