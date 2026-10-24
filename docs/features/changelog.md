# Changelog

`cerebrofy changelog` generates a semantic changelog from the call graph — classified from drift records, blast radius, agent memories, and product intent, never from commit messages.

## What It Is

Unlike traditional changelogs that parse commit messages, Cerebrofy's changelog classifies changes from the **semantic graph**. It detects which neurons were added, removed, or had signatures changed, then classifies each change into entry types (`feat`, `fix`, `refactor`, `security`, `breaking`, `perf`, `internal`, `intent_update`).

## CLI Reference

```bash
cerebrofy changelog --since v1.2.0                              # developer-level markdown
cerebrofy changelog --since last-build --audience pm            # PM-level, no code
cerebrofy changelog --since v1.2.0 --audience user              # plain-English, user-facing
cerebrofy changelog --since v1.2.0 --format github              # GitHub release body
cerebrofy changelog --since v1.2.0 --format slack               # Slack announcement
cerebrofy changelog --narrative --since project-start           # also write narrative_events rows
```

- `--since` — accepts a git tag, commit hash, `last-build` (commit of the newest health snapshot), or `project-start` (root commit)
- `--audience` — `developer` (default), `pm`, or `user`
- `--format` — `markdown` (default), `github`, or `slack`
- `--narrative` — persist every entry into the `narrative_events` table (feeds the Narrative Engine, Idea #26)

Error codes: `NO_INDEX` (no index found — run `cerebrofy build` first) and `REF_NOT_FOUND` (unknown git ref).

## MCP Tool: `cerebrofy_changelog`

**Input schema:**

```json
{
  "since": "v1.2.0",
  "audience": "pm",
  "format": "slack"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `since` | string | ✅ | Start point: git tag, commit hash, `last-build`, or `project-start` |
| `audience` | string | — | Target prose audience: `developer` (default), `pm`, or `user` |
| `format` | string | — | Output format: `markdown` (default), `github`, or `slack` |

**Output schema:**

```json
{
  "since": "v1.2.0",
  "until": "a1b2c3d4e5f6...",
  "entries": [
    {
      "type": "feat",
      "title": "Added new_feature",
      "description": "src/api/views.py::new_feature (added). Callers: 0 direct...",
      "neurons": ["src/api/views.py::new_feature"],
      "blast_radius": 0,
      "audience_text": "**new_feature** (src/api/views.py): Added new_feature."
    }
  ],
  "breaking_changes": [
    {
      "title": "BREAKING: validate_token changed",
      "description": "src/auth/tokens.py::validate_token (signature_changed)...",
      "neurons": ["src/auth/tokens.py::validate_token"]
    }
  ],
  "health_delta": { "coupling": 0.3, "avg_blast": 2.0 },
  "full_text": "## Changelog v1.2.0 → a1b2c3d\n..."
}
```

## Entry Types and Triggers

| Type | Trigger |
|------|---------|
| `feat` | New neuron with no predecessor in the index |
| `fix` | Structural change to an existing neuron with a warning memory |
| `refactor` | Same name removed from one lobe, added in another |
| `security` | Security/CVE-tagged memories on a changed neuron |
| `breaking` | Removal with callers · signature change on public surface · >3 cross-lobe callers |
| `perf` | Performance-tagged memories on a changed neuron |
| `internal` | No other signal matched |
| `intent_update` | `.cerebrofy/intent.yaml` changed in range (#23) |

Breaking changes are listed separately in `breaking_changes[]` so release notes never miss them.

## Data Flow

```
resolve_range()              ← git tag/hash ↔ commit hash
                              raises ChangelogError(REF_NOT_FOUND) if the ref is missing
    │
    ▼
detect_changes_between_refs() ← git diff --name-status since_ref..until_ref
    │
    ├── DriftRecord per file from classify_drift
    │     reads: nodes.name, nodes.signature, nodes.type, file_hashes
    │     returns: neuron-level change kind (added/removed/signature_changed)
    │
    ▼
collect_changes()            ← NeuronChange list (file, name, lobe, kind)
    │
    ▼
classify_changes()           ← breaking-first precedence:
                                added → breaking → security → perf → fix → internal
                                refactor for cross-lobe moves
    │
    ▼
build_entries()              ← ordered ChangelogEntry list per audience
    │
    ▼
format_changelog()           ← markdown | github | slack
    │
    ▼
ChangelogReport.to_dict()    ← exact spec schema
```

## Narrative Events (#26 feed)

With `--narrative`, each entry is written to the `narrative_events` table (migration `006_narrative_events.sql`, managed by `ensure_narrative_schema()`). Event IDs are deterministic per `(commit_ref, type, title)`, so re-running the same range replaces rows instead of duplicating them. The Narrative Engine (#26) reads this table to synthesise eras and stories — this lane only writes.

> **Template-based generation only.** The optional LLM-assisted path is not implemented (see `# TODO(llm)` markers in `generator.py`).

## Integration Points

- **Narrative Engine** — `--narrative` writes to `narrative_events` table
- **Health** — `health_delta` is included in changelog reports
- **Memory** — security/perf-tagged memories influence entry classification

## Related

- [Narrative](./narrative.md) — Codebase Narrative Engine that reads narrative_events
- [Health](./health.md) — health snapshots feed changelog health_delta
- [Memory](./memory.md) — memory-tagged changes influence classification