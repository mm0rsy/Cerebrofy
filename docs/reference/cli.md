# CLI Reference

Complete reference for all `cerebrofy` commands. Commands are grouped by category.

## Project Setup

### `cerebrofy init`

Scaffold `.cerebrofy/`, auto-detect Lobes, install git hooks, and register the MCP server.

```bash
cerebrofy init                           # Local MCP registration (default)
cerebrofy init --global                  # Register MCP globally (~/.config/mcp/servers.json)
cerebrofy init --no-mcp                  # Skip MCP registration
cerebrofy init --force                   # Re-initialize, overwrite MCP entry with current binary path
cerebrofy init --ai claude               # Also write AI navigation rules to CLAUDE.md
cerebrofy init --ai copilot              # Also write rules to .github/copilot-instructions.md
cerebrofy init --ai vscode               # Same as --ai copilot
cerebrofy init --ai opencode             # Also write rules to .opencode/instructions.md
```

**What it creates:**

```
.cerebrofy/
├── config.yaml          ← Lobe map, tracked extensions, embed model
├── arch-rules.yaml      ← Architecture drift rules (scaffolded sample)
├── db/                  ← cerebrofy.db lives here (gitignored)
└── queries/             ← Tree-sitter .scm files per language
.cerebrofy-ignore        ← Ignore rules (gitignore syntax)
.gitignore               ← .cerebrofy/db/ appended automatically
.git/hooks/pre-commit    ← Auto-runs cerebrofy update + arch check on every commit
.git/hooks/pre-push      ← Validates index + runs the arch check before push
.git/hooks/post-merge    ← state_hash sync check after git pull
```

### `cerebrofy migrate`

Run sequential schema migration scripts.

```bash
cerebrofy migrate
```

Scripts live in `.cerebrofy/scripts/migrations/`. Safe to run multiple times — already-applied migrations are skipped.

## Indexing

### `cerebrofy build`

Full atomic re-index of the repository.

```bash
cerebrofy build
```

Writes to `cerebrofy.db.tmp`, swaps atomically to `cerebrofy.db` only on success. Runs 6 steps (see [Architecture](../concepts/architecture.md#data-flow)).

### `cerebrofy update`

Partially re-index only changed files — target latency < 2s for a single-file change.

```bash
cerebrofy update                        # Auto-detect via git
cerebrofy update src/auth/login.py      # Explicit file list
```

### `cerebrofy validate`

Classify drift between the index and current source.

```bash
cerebrofy validate
```

Exit codes: `0` = clean/minor drift; `1` = structural drift.

## Analysis

### `cerebrofy blast-radius`

Compute the blast radius of a function or class — every caller at depth 1 and 2, test coverage gaps, lobe spread, and a risk score.

```bash
cerebrofy blast-radius validate_token
cerebrofy blast-radius src/auth/tokens.py::validate_token --depth 3
cerebrofy blast-radius validate_token --format markdown
```

See [Blast Radius](../features/blast-radius.md).

### `cerebrofy context`

Build the optimal context window for a coding task within a token budget. Uses KNN + BFS to find relevant Neurons, then greedy-packs them by relevance with tier degradation.

```bash
cerebrofy context "add rate limiting to the payments API"
cerebrofy context "refactor auth module" --budget 12000
cerebrofy context "fix token expiry bug" --output claude-xml
```

### `cerebrofy epistemic`

Show the epistemic confidence score and staleness warnings for the current index.

```bash
cerebrofy epistemic
cerebrofy epistemic --json   # machine-readable output for agent consumption
```

### `cerebrofy health`

Show longitudinal codebase health metrics derived from the call graph, with deltas vs the previous build.

```bash
cerebrofy health                      # current snapshot vs last build
cerebrofy health --history 30         # last 30 builds in a table
cerebrofy health --trend coupling     # ASCII sparkline for a metric over time
cerebrofy health --export json        # machine-readable snapshot
cerebrofy health --watch              # live-update: re-renders after each build
```

See [Health](../features/health.md).

### `cerebrofy impact`

Predict the full blast radius of a refactor **before touching any code**. Runs BFS caller traversal, maps test coverage, estimates lines of code affected, and produces a recommended refactoring sequence.

```bash
cerebrofy impact auth/tokens.py::validate_token
cerebrofy impact validate_token --depth 3
cerebrofy impact auth/tokens.py:42 --no-sequence
cerebrofy impact auth/tokens.py::validate_token --output json
```

### `cerebrofy plan`

Generate a step-by-step, graph-aware refactoring plan from a plain-English description — *before touching any code*.

```bash
cerebrofy plan "extract the payment logic into a payments service"
cerebrofy plan "move all database connection code into a db/ module"
cerebrofy plan "extract the auth helpers" --output json
cerebrofy plan "extract the auth helpers" --execute
```

The plan is a human-in-the-loop pre-flight checklist. `dry_run` defaults to true — **no files are ever modified** by the planner.

### `cerebrofy review`

Graph-aware code review for a local diff or a GitHub PR — blast radius, warning memories and past decisions, architecture rules, coverage gaps, missing caller updates, cross-lobe coupling, and knowledge-silo reviewers in one report.

```bash
cerebrofy review --diff HEAD~1                 # local pre-merge review
cerebrofy review --diff HEAD                   # uncommitted changes
cerebrofy review --pr 142                      # dry-run PR review (nothing posted)
cerebrofy review --pr 142 --severity error     # blocking findings only
cerebrofy review --pr 142 --post-comments      # post inline comments + PR summary
cerebrofy review --pr 142 --format json        # machine-readable output
```

See [Review](../features/review.md).

### `cerebrofy silo`

Identify knowledge silos — functions with high blast radius owned by few contributors.

```bash
cerebrofy silo                              # full report, top 20 silos
cerebrofy silo --top 10 --min-callers 3
cerebrofy silo --lobe auth
cerebrofy silo --author alice@company.com
cerebrofy silo --risk high
cerebrofy silo --write-memories
cerebrofy silo --output json
```

See [Silo Detection](../features/silo-detection.md).

### `cerebrofy vuln`

Map which of your functions are exposed to a vulnerable package.

```bash
cerebrofy vuln --package requests
cerebrofy vuln --package requests --function requests.get
cerebrofy vuln --package pyyaml --write-memories
cerebrofy vuln --package requests --depth 3 --output json
```

See [Vulnerability](../features/vulnerability.md).

### `cerebrofy coverage-gap`

Rank uncovered neurons by blast radius × change velocity.

```bash
cerebrofy coverage-gap
cerebrofy coverage-gap --days 14
cerebrofy coverage-gap --min-blast 2
cerebrofy coverage-gap --lobe auth
cerebrofy coverage-gap --risk critical
cerebrofy coverage-gap --write-memories
cerebrofy coverage-gap --output json
```

See [Coverage Gap](../features/coverage-gap.md).

### `cerebrofy upgrade`

Plan a dependency upgrade from a curated breaking-change manifest.

```bash
cerebrofy upgrade pydantic --from v1 --to v2
cerebrofy upgrade requests --breaking-only
cerebrofy upgrade pydantic --manifest ./pydantic.yaml --auto-fix --step 1,2
cerebrofy upgrade pydantic --validate
```

See [Upgrade](../features/upgrade.md).

### `cerebrofy onboard`

Generate a personalized onboarding guide from the cerebrofy index.

```bash
cerebrofy onboard                          # generates .cerebrofy/ONBOARDING.md
cerebrofy onboard --name "Alice"
cerebrofy onboard --focus auth
cerebrofy onboard --format html
cerebrofy onboard --depth senior
cerebrofy onboard --output ~/ONBOARDING.md
```

See [Onboarding](../features/onboarding.md).

## Memory

### `cerebrofy memory`

Write and query structured memories attached to neurons and lobes.

```bash
cerebrofy memory add "Clock skew breaks token expiry" \
    --type warning --neuron auth/tokens.py::validate_token --tags "security,jwt"
cerebrofy memory search "JWT expiry edge cases" --lobe auth
cerebrofy memory list --lobe auth --type warning
cerebrofy memory link <from-id> <to-id> --rel motivated
cerebrofy memory export --format markdown > DECISIONS.md
```

See [Memory](../features/memory.md).

### `cerebrofy intent`

Manage the product intent declaration file (`.cerebrofy/intent.yaml`).

```bash
cerebrofy intent init        # scaffold intent.yaml with commented sections
cerebrofy intent show        # display current intent (human-readable)
cerebrofy intent show --json # machine-readable for agent consumption
cerebrofy intent edit        # open in $EDITOR
cerebrofy intent validate    # check YAML + validate lobe names against graph
```

### `cerebrofy changelog`

Generate a semantic changelog from the call graph.

```bash
cerebrofy changelog --since v1.2.0
cerebrofy changelog --since last-build --audience pm
cerebrofy changelog --since v1.2.0 --audience user
cerebrofy changelog --since v1.2.0 --format github
cerebrofy changelog --since v1.2.0 --format slack
cerebrofy changelog --narrative --since project-start
```

See [Changelog](../features/changelog.md).

### `cerebrofy synthesize`

Cross-Session Synthesizer: detect failure/success patterns, lobe fragility, effort calibration, and agent blind spots from recorded sessions.

```bash
cerebrofy synthesize --run
cerebrofy synthesize --show
cerebrofy synthesize --show --confidence 0.8
cerebrofy synthesize --run --min-sessions 5
```

See [Synthesizer](../features/synthesizer.md).

### `cerebrofy narrative`

Read or regenerate the codebase narrative — architectural eras, significant events, architectural DNA, and intent-driven trajectory.

```bash
cerebrofy narrative
cerebrofy narrative --era 2
cerebrofy narrative --since 2026-01-01
cerebrofy narrative --update
```

See [Narrative](../features/narrative.md).

### `cerebrofy insights`

Show insights from the Insight Daemon, or force a daemon run.

```bash
cerebrofy insights
cerebrofy insights --type trend_alert
cerebrofy insights --since 7d
cerebrofy insights --run
cerebrofy insights --min-confidence 0.8
```

See [Insights](../features/insights.md).

## Sessions

### `cerebrofy session`

Record, replay, and audit AI agent sessions.

```bash
cerebrofy session list                                   # list recorded sessions
cerebrofy session show sess_abc123                       # full replay (latest when omitted)
cerebrofy session diff sess_abc123                       # graph changes the session made
cerebrofy session search "rate limiting"                 # semantic search across session tasks
cerebrofy session export sess_abc123 --format html       # shareable self-contained HTML report
```

See [Sessions](../features/sessions.md).

### `cerebrofy who`

See who is active and what they claimed.

```bash
cerebrofy who [--format text|json]
```

### `cerebrofy claim`

Claim a neuron before editing it.

```bash
cerebrofy claim auth/tokens.py::validate_token \
    --intent "refactoring to add strict mode" \
    --agent-id claude-sess-001
```

### `cerebrofy release`

Release claims when the edit is done.

```bash
cerebrofy release auth/tokens.py::validate_token --agent-id claude-sess-001
```

### `cerebrofy conflicts`

Check for claim and memory conflicts.

```bash
cerebrofy conflicts
```

### `cerebrofy resolve`

Resolve a pair of contradicting memories.

```bash
cerebrofy resolve MEMORY_A MEMORY_B --keep newest|author|human-review
cerebrofy resolve MEMORY_A MEMORY_B --merge --body TEXT [--author NAME]
```

See [Coordination](../features/coordination.md).

## Architecture Rules

### `cerebrofy arch`

Enforce architecture rules as queries over the live call graph.

```bash
cerebrofy arch init                                         # interactive rule builder
cerebrofy arch check                                        # all rules; exit 1 on error-severity violations
cerebrofy arch check --rule no-direct-db-in-api
cerebrofy arch check --since HEAD~1 --format github-annotations
cerebrofy arch check --write-memories                       # record violations as warning memories
cerebrofy arch explain no-direct-db-in-api                  # rule definition + every current violation
cerebrofy arch history                                      # when each rule was first violated
cerebrofy arch watch --interval 2                           # live terminal monitor
```

## MCP Server

### `cerebrofy mcp`

Start the MCP stdio server. Used by AI tools (Claude Desktop, Cursor, VS Code, etc.) — not invoked manually.

```bash
cerebrofy mcp    # requires: uv tool install "cerebrofy[mcp]"
```

### `cerebrofy viz`

Launch an interactive **3D brain visualization** of your codebase's call graph in the browser.

```bash
cerebrofy viz
# → Serving at http://localhost:7331
```

## Error Codes

Common error codes across commands:

| Code | Meaning |
|------|---------|
| `NO_INDEX` | `.cerebrofy/db/cerebrofy.db` missing; run `cerebrofy build`. |
| `REF_NOT_FOUND` | Unknown git ref (tag, hash, or branch). |
| `CLUSTER_TOO_SMALL` | Fewer than 2 neurons matched — refine the query (`cerebrofy plan`). |
| `CLUSTER_TOO_LARGE` | More than 200 neurons matched — scope more narrowly (`cerebrofy plan`). |
| `NO_SESSION_RECORDER` | Session recording disabled (`record_sessions: true` required). |
| `SESSION_NOT_FOUND` | Requested session id does not exist. |
| `NO_ACTIVE_SESSION` | Session is already ended. |
| `NO_ACTIVE_AGENT` | `release` called for an agent id with no active registration. |
| `NEURON_ALREADY_CLAIMED` | Requested neurons are claimed by another active agent. |
| `CLAIM_EXPIRED` | Claim TTL elapsed before work finished. |
| `CONFIG_ERROR` | Invalid arguments (e.g. missing merge body or author). |
| `INSUFFICIENT_HISTORY` | Fewer than 3 health snapshots for narrative generation. |
| `NO_RULES_FILE` | No `.cerebrofy/arch-rules.yaml` found (offer `cerebrofy arch init`). |
| `NO_GOVERNANCE_RULES` | No `governance.rules` block in arch-rules.yaml. |
| `NO_INTENT_FILE` | `.cerebrofy/intent.yaml` does not exist. |
| `MANIFEST_NOT_FOUND` | No manifest exists for the package (`cerebrofy upgrade`). |
| `INVALID_MANIFEST` | Manifest is malformed (`cerebrofy upgrade`). |
| `VERSION_NOT_FOUND` | Manifest exists but doesn't cover the requested version pair (`cerebrofy upgrade`). |
| `PACKAGE_NOT_USED` | Package not used in any indexed file (`cerebrofy upgrade`). |
| `GH_NOT_AUTHENTICATED` | `gh` CLI missing or not logged in. |
| `NO_DIFF_PROVIDED` | Neither `diff` nor `pr` given (`cerebrofy review`). |