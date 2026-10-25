---
name: cerebrofy-narrative
description: "Read the story of the codebase — how it evolved, what changed it, and where it is going."
---

# Skill: cerebrofy-narrative

> Read the story of the codebase — how it evolved, what changed it, and where it is going.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase's history.**

Cerebrofy already keeps `.cerebrofy/NARRATIVE.md` and the structured
`cerebrofy_narrative` MCP tool. Start there before reading any code.

## When to use

- At the start of a session, before proposing architectural changes
- When asked "why is the codebase like this?" or "what changed recently?"
- Before a refactor that may contradict a past decision or incident
- When onboarding a new agent or developer and you need historical context

## How to use via MCP

```
cerebrofy_narrative()
cerebrofy_narrative(section="eras")
cerebrofy_narrative(section="trajectory")
cerebrofy_narrative(era=2)
cerebrofy_narrative(update=true)
```

The tool returns:

- `narrative_markdown` — the full document, or the requested section
- `era_count` — number of detected architectural eras
- `event_count` — number of significant events woven into the story
- `last_updated` — unix timestamp of the rendered document
- `current_era` — `name`, `started` (ISO date), `key_changes`,
  `structural_state` (`lobes`, `neurons`, `coupling`, `avg_blast_radius`)

## How to use via CLI

```bash
cerebrofy narrative                    # display NARRATIVE.md
cerebrofy narrative --update           # force regeneration
cerebrofy narrative --era 2            # show a specific era
cerebrofy narrative --since 2026-01-01 # events since a date
```

## Reading the output as an AI agent

- **Eras** are periods of structural stability separated by large metric shifts
  (coupling > 10%, blast radius > 20%, or a lobe-count change).
- **Significant events** merge changelog `narrative_events` with
  decision/warning/incident memories — treat them as the "why".
- **Architectural DNA** reflects enforced arch rules and long-term health trends.
- **Where It's Going** comes from `intent.yaml`; it is the team's current direction.

Generation needs at least three health snapshots. If the tool returns
`INSUFFICIENT_HISTORY`, suggest running `cerebrofy update` a few times (or
`cerebrofy build`) to accumulate history.

## Quick reference

| Goal | MCP call |
|------|---------|
| Full story | `cerebrofy_narrative()` |
| Every era | `cerebrofy_narrative(section="eras")` |
| Current direction | `cerebrofy_narrative(section="trajectory")` |
| One era | `cerebrofy_narrative(era=2)` |
| Regenerate now | `cerebrofy_narrative(update=true)` |
