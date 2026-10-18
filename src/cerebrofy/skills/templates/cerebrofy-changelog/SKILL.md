````markdown
# Skill: cerebrofy-changelog

> Semantic changelog: what actually changed in the codebase — classified from the
> call graph, drift records, and memories, never from commit messages.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use this skill

Invoke `/cerebrofy:changelog` when you need to:
- Draft release notes from a git range (`--since <tag|hash|last-build>`)
- Produce a PM- or user-facing summary of what changed (`--audience pm|user`)
- Format a changelog for GitHub releases or a Slack announcement (`--format github|slack`)
- Feed the narrative timeline with structured events (`--narrative`)

## How to run

```bash
cerebrofy changelog --since v1.2.0                            # developer-level markdown
cerebrofy changelog --since v1.2.0 --audience pm              # PM-level, no code
cerebrofy changelog --since last-build --audience user        # plain-English, user-facing
cerebrofy changelog --since v1.2.0 --format github            # GitHub release body
cerebrofy changelog --since v1.2.0 --format slack             # Slack announcement
cerebrofy changelog --narrative --since project-start         # write narrative_events rows
```

Or via MCP tool:

```
cerebrofy_changelog(since="v1.2.0", audience="pm", format="slack")
```

## How to interpret results

Every entry carries a semantic **type** derived from the graph:

| Type | Trigger |
|------|---------|
| `feat` | New neuron (no predecessor in the index) |
| `fix` | Structural change to an existing neuron with a warning memory |
| `refactor` | Neuron moved across lobes |
| `security` | Neuron with security/CVE-tagged memories changed (#08) |
| `breaking` | >3 cross-lobe callers, signature change on a public surface, or removal with callers |
| `perf` | Neuron with performance-tagged memories changed |
| `internal` | Everything else — no user impact |
| `intent_update` | `.cerebrofy/intent.yaml` changed in the range (#23) |

Breaking changes are listed separately in `breaking_changes[]` so release notes never miss them.

## Recommended follow-up actions

1. For every `breaking` entry, run `cerebrofy impact <neuron>` to enumerate callers that must be updated.
2. Quote the memories attached to `fix`/`security` entries as the "why" in release notes.
3. Use `--narrative` on release ranges so the narrative engine (#26) can synthesise eras later.
````
