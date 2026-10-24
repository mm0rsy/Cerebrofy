---
name: cerebrofy-synthesize
description: Run or inspect the Cerebrofy Cross-Session Synthesizer to learn recurring failure and success patterns from recorded agent sessions.
author: cerebrofy
version: 1.0.0
---

# Cerebrofy Synthesize Skill

This skill exposes the Cross-Session Synthesizer (Idea #24). It reads every
recorded session (Idea #11), runs five statistical detectors, and persists
actionable patterns as `type=pattern, tag=synthesized` memories (Idea #05).
Those memories are then attached to `get_neuron` and `cerebrofy_impact`
responses.

## Commands

| Slash Command | MCP Tool | Description |
|---|---|---|
| `/cerebrofy:synthesize` | `cerebrofy_synthesize` with `{"run_now": true}` | Run synthesis now |
| `/cerebrofy:synthesize --show` | `cerebrofy_synthesize` with `{"run_now": false}` | Show existing patterns only |
| `/cerebrofy:synthesize --confidence 0.8` | `cerebrofy_synthesize` with `{"min_confidence": 0.8}` | Filter by persisted confidence |
| `/cerebrofy:synthesize --min-sessions 5` | `cerebrofy_synthesize` with `{"min_sessions": 5}` | Lower the session gate |

## Pattern Types

- **failure_correlation** — a tool sequence associated with a higher failure rate
- **lobe_fragility** — a lobe whose sessions fail more than 70% of the time
- **effort_calibration** — measured actual/predicted blast-radius ratio for upgrades
- **missing_step** — a tool sequence associated with a higher success rate
- **agent_blind_spot** — a module agents consistently miss when changing another module

Patterns persist their confidence, session count, and sample size as
machine-readable tags, so `--confidence` filters stored patterns as well as
fresh results. Automatic scheduling is count-based; the API reports
`sessions_until_next_synthesis` and `next_synthesis_at: null`.

## Usage Examples

```
/cerebrofy:synthesize
/cerebrofy:synthesize --confidence 0.8
/cerebrofy:synthesize --show
```

## Agent Invocation

```
Use cerebrofy_synthesize with arguments: {"run_now": true, "show_patterns": true}
Use cerebrofy_synthesize with arguments: {"min_confidence": 0.8}
```

## Hooks

Synthesis is triggered non-fatally after every N closed sessions:

- `cerebrofy_session_end` checks the closed-session count
- the Insight Daemon (#21) checks again at the end of `cerebrofy build`

The interval is configurable as `synthesis.every_n_sessions` (default `10`).

## Configuration

```yaml
synthesis:
  every_n_sessions: 10
```

Requires `record_sessions: true` so that `sessions.db` exists.
