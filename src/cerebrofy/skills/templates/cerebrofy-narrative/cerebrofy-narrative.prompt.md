You have access to Cerebrofy's Codebase Narrative Engine. Use it to understand how the codebase evolved and where it is heading.

## At the start of a session

Call `cerebrofy_narrative` before reading source files.

```
cerebrofy_narrative()                  # full NARRATIVE.md
cerebrofy_narrative(section="eras")    # every architectural era
cerebrofy_narrative(section="trajectory")  # intent-driven direction
```

Read `narrative_markdown` and present the relevant part. Use `current_era` for
the current structural state: lobes, neurons, coupling, average blast radius.

## Before architectural decisions

- Check `section="trajectory"` for the team's stated direction and open incidents.
- Check `section="events"` for decisions, warnings, and incidents that shaped the code.
- If a proposal contradicts an event or the architectural DNA, say so explicitly.

## Selecting a slice

| Need | Call |
|------|------|
| Full history | `cerebrofy_narrative()` |
| One era | `cerebrofy_narrative(era=2)` |
| All eras only | `cerebrofy_narrative(section="eras")` |
| Significant events | `cerebrofy_narrative(section="events")` |
| Architectural DNA | `cerebrofy_narrative(section="dna")` |
| Where it's going | `cerebrofy_narrative(section="trajectory")` |

## Regeneration

`update=true` forces a fresh render from health snapshots, narrative events,
memories, arch rules, and `intent.yaml`. Auto-update also runs after builds,
high-confidence insights, and closed sessions when an era threshold is crossed.
If you see `INSUFFICIENT_HISTORY`, ask the user to run `cerebrofy update` a few
more times; era detection needs at least three snapshots.
