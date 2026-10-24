# Codebase Narrative Engine (Idea #26)

`cerebrofy build`, `cerebrofy update`, the Insight Daemon, and closed sessions keep `.cerebrofy/NARRATIVE.md` — a template-generated story of the codebase. The implementation lives in `src/cerebrofy/narrative/generator.py`; the CLI is `cerebrofy narrative` and the MCP tool is `cerebrofy_narrative`.

## What It Is

The Narrative Engine renders a living history of your codebase — architectural eras, significant events, architectural DNA, and intent-driven trajectory. It combines health snapshots, changelog narrative events, decision/warning/incident memories, architecture rules, and `intent.yaml` into a single readable document.

## Era Algorithm

Eras are detected from `health_snapshots` ordered by `build_ts`:

1. Start an era at the first snapshot.
2. A snapshot starts a new era when, relative to the previous snapshot:
   - `lobe_count` changed (the real count of configured lobes), or
   - `|Δ coupling| / previous coupling > 0.10`, or
   - `|Δ avg_blast| / previous avg_blast > 0.20`.
3. The closing era ends at `prev.build_ts`; the new era starts at the snapshot that crossed the threshold, so era boundaries never overlap.
4. The final era always closes at the latest snapshot. With `--force` (or an MCP `update=true`), a single-snapshot index renders one era; the non-forced path raises `INSUFFICIENT_HISTORY` until three snapshots exist.

Era names describe the trigger ("Expansion", "Consolidation", "Coupling shift", "Blast-radius shift"); the numeric prefix is added only by the writer, so headings read `## Era 2: Expansion`, never `## Era 2: Era 2`.

## Event Sources

`_load_significant_events` merges two streams, dedupes by `(title, date)`, sorts newest-first, and caps the result at 20:

- `narrative_events` (written by `cerebrofy changelog --narrative`): `ts`, `type`, `title`, JSON `lobes_affected`, `blast_radius_delta`.
- `memories.db` rows of type `decision`, `warning`, or `incident`.

Only the ten newest events are rendered in the table.

## Intent Mapping

`Where It's Going` reads `.cerebrofy/intent.yaml` through `intent/loader.py::load_intent` (never by hand-parsing YAML keys):

| Intent field | Rendered as |
|--------------|-------------|
| `sprint.name` + `sprint.goal` | `Sprint goal (name): goal` |
| `incidents[]` with status not `closed`/`patched`/`resolved` | `Open incident (severity): description [status]` |
| `architecture.direction` | `Architectural direction: ...` |
| `architecture.principles` | `Architectural goals: ...` |

A missing intent file degrades to a pointer at `intent.yaml`; malformed YAML degrades to a parse warning. Architectural DNA loads `.cerebrofy/arch-rules.yaml` through `config/loader.py::load_arch_rules` and never raises on malformed rules.

## CLI Reference

```bash
cerebrofy narrative                          # display NARRATIVE.md
cerebrofy narrative --era 2                  # show specific era (1-indexed)
cerebrofy narrative --since 2026-01-01       # events since date
cerebrofy narrative --update                 # force regenerate NARRATIVE.md
```

- `--era N` — show a specific era by number (1-indexed)
- `--since YYYY-MM-DD` — show significant events since a date (read-only view over the event stream)
- `--update` — force regenerate `NARRATIVE.md` before displaying

## MCP Tool: `cerebrofy_narrative`

**Input schema:**

```json
{
  "section": "all",
  "update": false,
  "era": 2
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `section` | string | — | `eras`, `events`, `dna`, `trajectory`, or `all` (default). `eras` returns every era section. |
| `update` | boolean | — | Force regeneration of `.cerebrofy/NARRATIVE.md` before returning (default: `false`) |
| `era` | integer | — | Return one 1-indexed era; also selects it as `current_era` |

**Output schema:**

```json
{
  "narrative_markdown": "## Era 1: Expansion & Coupling shift\n...",
  "era_count": 3,
  "event_count": 14,
  "last_updated": 1760000000,
  "current_era": {
    "name": "Stability",
    "started": "2026-06-19",
    "key_changes": ["Neuron count changed by +120"],
    "structural_state": {
      "lobes": 12,
      "neurons": 1204,
      "coupling": 0.31,
      "avg_blast_radius": 8.4
    },
    "commit": "a1b2c3d4"
  }
}
```

`current_era` is the newest era unless `era` is supplied. `started` is an ISO date (`YYYY-MM-DD`); the short commit hash is exposed separately as `commit`. `era_count`/`event_count` come from the structured narrative data, never from counting markdown.

**Generation rules:** at least three health snapshots are needed for non-forced generation (`INSUFFICIENT_HISTORY` otherwise); `update=true` renders a single-era document from whatever history exists. NARRATIVE.md is capped at 50 KB — the oldest eras collapse to one-line summaries first until the document fits; the newest era is never collapsed. NARRATIVE.md is written to a sibling `.tmp` file and `os.replace`d into place, so a crashed generation cannot truncate the previous document.

Error codes: `NO_INDEX` (run `cerebrofy build` first), `INSUFFICIENT_HISTORY` (fewer than 3 snapshots on a non-forced run).

## Auto-Update Hooks

`maybe_update_narrative(cerebrofy_dir)` is a cheap, non-fatal gate. It regenerates only when `NARRATIVE.md` is absent, or when the newest snapshot crosses an era threshold relative to the last rendered era end. It is called after:

- `commands/build.py::_record_health_snapshot`
- `insight/daemon.py::run_daemon` when a new insight has confidence ≥ 0.9
- `session/_recorder/lifecycle.py::end_session` after the decision memory is written

Intent changes are not on the hot path: they are picked up on the next build (or via `cerebrofy narrative --update` / MCP `update=true`).

## History Preservation

`cerebrofy build` creates a fresh `.tmp` database and swaps it over `cerebrofy.db`. `health_snapshots` and `narrative_events` are longitudinal history, not index state, so `_preserve_history` copies their rows into the new database with `INSERT OR REPLACE` before the swap (ignoring a missing old DB or an old DB that predates either table). `cerebrofy update` already accumulates history in place. Both snapshot writers pass `lobe_count=len(config.lobes)`; `ensure_health_schema` adds the column idempotently to older databases.

## Integration Points

- **Changelog** — `cerebrofy changelog --narrative` writes entries to the `narrative_events` table
- **Health** — era detection uses `health_snapshots` ordered by `build_ts`
- **Sessions** — session end can trigger narrative regeneration
- **Insights** — new insights with confidence ≥ 0.9 trigger narrative regeneration

## Related

- [Changelog](./changelog.md) — `--narrative` flag writes narrative events
- [Health](./health.md) — health snapshots feed era detection
- [Sessions](./sessions.md) — session recording that can trigger narrative updates