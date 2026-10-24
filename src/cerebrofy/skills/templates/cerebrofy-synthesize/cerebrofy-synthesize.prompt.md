# Cerebrofy Synthesize Prompt

You are an AI agent with access to the Cerebrofy Cross-Session Synthesizer — a
reflection layer that reads all recorded agent sessions and turns recurring
outcomes into reusable pattern memories.

## When to Use This Skill

- After completing a batch of sessions to extract lessons learned
- Before starting work in a lobe with a known fragility pattern
- When a session failed and you want to know whether the failure mode recurs
- When planning a refactor or dependency upgrade and checking calibration data

## Available Commands

```
/cerebrofy:synthesize                     # Run synthesis now
/cerebrofy:synthesize --show              # Show existing patterns only
/cerebrofy:synthesize --confidence 0.8    # Filter by persisted confidence
/cerebrofy:synthesize --min-sessions 5    # Lower the session gate
```

## MCP Tool

```json
{
  "name": "cerebrofy_synthesize",
  "arguments": {
    "run_now": true,
    "show_patterns": true,
    "min_sessions": 10,
    "min_confidence": 0.7
  }
}
```

## Response Format

The tool returns structured JSON with:

- `patterns_found`: patterns detected this run (or persisted patterns on read)
- `patterns_written`: newly inserted patterns (0 on read and on idempotent runs)
- `patterns`: array of `{type, title, confidence, body, sessions_analyzed, sample_size, lobe}`
- `sessions_analyzed`: closed sessions considered by the run
- `sessions_until_next_synthesis`: closed sessions remaining before the next auto-trigger
- `next_synthesis_at`: always `null` — scheduling is session-count based, not time based

## Best Practices

1. **Run on demand with `run_now: true`** after a batch of sessions.
2. **Use `min_confidence: 0.8`** for high-signal patterns; the filter applies to
   patterns already persisted, not just fresh detections.
3. **Re-run safely** — deterministic pattern ids make synthesis idempotent;
   identical patterns are not duplicated and keep their original `created_ts`.
4. **Expect `sessions_until_next_synthesis`** rather than a wall-clock time for
   automatic runs. Configure the cadence with `synthesis.every_n_sessions`.

## Pattern Types Reference

| Type | Trigger | Typical Action |
|---|---|---|
| failure_correlation | Tool sequence lift > 2.0, sample >= 5 | Add the missing guard step |
| lobe_fragility | Lobe failure rate > 70%, sample >= 5 | Stricter checks in that lobe |
| effort_calibration | Mean actual/predicted > measured, confidence >= 0.80, sample >= 5 | Adjust upgrade estimates |
| missing_step | Success lift > 2.0, both classes >= 5 | Sequence the successful step |
| agent_blind_spot | Pair co-occurs in >= 5 successes; failure rate >= 85% | Always update the missed module |

---

*Auto-installed by Cerebrofy. Skill file: `cerebrofy-synthesize/SKILL.md`*
