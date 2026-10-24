# Cross-Session Synthesizer (Idea #24)

The synthesizer turns the session log (Idea #11) into reusable knowledge. It reads closed sessions from `.cerebrofy/db/sessions.db`, runs five statistical detectors, and persists the results as `type=pattern` memories in `memories.db` with tags `synthesized,<type>,confidence=…,sessions=…,sample=…`.

## What It Is

The Cross-Session Synthesizer analyzes recorded agent sessions to detect recurring patterns — failures, fragile lobes, effort miscalibrations, missing steps, and agent blind spots. The patterns are persisted as memories so future agents can benefit from past experience.

## Detectors and Thresholds

| Detector | Signal | Fires when |
|----------|--------|------------|
| `failure_correlation` | tool-sequence failure lift | `failure_rate_with / max(failure_rate_without, 0.01) > 2.0`, sample >= 5 |
| `lobe_fragility` | per-lobe failure rate | rate > 0.70, unique sessions >= 5 |
| `effort_calibration` | mean `actual / predicted` blast radius | sample >= 5, share over 2× >= 0.80 |
| `missing_step` | tool-sequence success lift | success lift > 2.0, both classes >= 5, candidates already flagged as failures excluded |
| `agent_blind_spot` | module-pair omission | pair co-occurs in >= 5 successes; sessions touching A but not B fail >= 85% of the time over >= 5 samples |

Patterns carry a deterministic id derived from `(type, title)`, so repeated runs update rather than duplicate. Updates keep the original `created_ts`; identical patterns are skipped entirely.

## CLI Reference

```bash
# Force a synthesis run now
cerebrofy synthesize --run

# Show existing synthesized patterns
cerebrofy synthesize --show

# Lower the confidence threshold
cerebrofy synthesize --show --confidence 0.5

# Lower the session gate
cerebrofy synthesize --run --min-sessions 5
```

- `--run` — force a synthesis run now (explicit alias)
- `--show` — read-only; show existing synthesized patterns (default when no other flag)
- `--min-sessions N` — minimum closed sessions before detectors run (default: 10)
- `--confidence N` — minimum confidence 0-1 (default: 0.7)

## MCP Tool: `cerebrofy_synthesize`

**Input schema:**

```json
{
  "run_now": false,
  "min_sessions": 10,
  "show_patterns": true,
  "min_confidence": 0.7
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `run_now` | boolean | — | Force a synthesis run before returning (default: `false`) |
| `min_sessions` | integer | — | Closed-session gate before detectors run (default: `10`) |
| `show_patterns` | boolean | — | Include the pattern array in the response (default: `true`) |
| `min_confidence` | number | — | Minimum **persisted** confidence, applied on read and run paths (default: `0.7`) |

**Output:** `patterns_found`, `patterns_written` (new inserts only; `0` on the read path and on idempotent reruns), `patterns[]` (each with `type`, `title`, `confidence`, `body`, `sessions_analyzed`, `sample_size`, `lobe`), `sessions_analyzed`, `sessions_until_next_synthesis`, and `next_synthesis_at`.

Automatic scheduling is session-count based, so `next_synthesis_at` is always `null`; the honest countdown is `sessions_until_next_synthesis`.

Pattern ids are deterministic per `(type, title)`, so reruns do not duplicate memories and preserve each pattern's original `created_ts`.

Error codes: `[NO_INDEX]` when no index exists; `[NO_SESSION_RECORDER]` when session recording is disabled (`record_sessions: true` is required).

## Configuration

```yaml
# .cerebrofy/config.yaml
synthesis:
  every_n_sessions: 10   # run after every N closed sessions
```

## Trigger

Synthesis runs automatically when the number of closed sessions crosses a multiple of `synthesis.every_n_sessions` (default `10`):

- `session/recorder/lifecycle.py::end_session` checks after each close when a `cerebrofy_dir` is supplied
- `insight/daemon.py::run_daemon` checks again at the end of `cerebrofy build`

Both hooks are non-fatal: no synthesis failure can break a session close or a build. `cerebrofy synthesize` and the `cerebrofy_synthesize` MCP tool force a run with `--run` / `run_now: true`.

## Storage and Consumers

Patterns live in `memories.db` (no new tables). Lobe-scoped detections (`lobe_fragility`, `agent_blind_spot`, and single-lobe failure correlations) set `memories.lobe`; the memory store's `list_synthesized_patterns()` helper parses confidence and sample metadata from tags.

- `get_neuron` responses gain a `patterns` key
- `cerebrofy_impact` reports patterns for every impacted lobe
- Existing response keys are unchanged

## Integration Points

- **Session recording** — requires `record_sessions: true`; closed sessions are the input data
- **Memory** — patterns are written as `type=pattern` memories in `memories.db`
- **Impact** — patterns are reported for every impacted lobe
- **Narrative** — session-derived patterns can surface in narrative events

## Error Codes

| Code | Meaning | Recovery |
|------|---------|----------|
| `NO_INDEX` | `.cerebrofy` not found | Run `cerebrofy build` first |
| `NO_SESSION_RECORDER` | Session recording disabled | Set `record_sessions: true` in config.yaml |

## Related

- [Sessions](./sessions.md) — session recording that feeds the synthesizer
- [Memory](./memory.md) — where patterns are persisted
- [Configuration](../getting-started/configuration.md) — `synthesis` and `record_sessions` config fields