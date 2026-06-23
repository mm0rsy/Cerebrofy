You have access to Cerebrofy's onboarding navigator. Use it to orient yourself or a new developer in any indexed repository.

## At the start of an onboarding session

Call `cerebrofy_onboard` immediately. Do not read files first.

```
cerebrofy_onboard(depth="junior")   # for a newcomer
cerebrofy_onboard(depth="senior")   # for an experienced engineer
```

Read the returned `markdown` field and present it. Use the `structured` field to answer follow-up questions.

## Calibrating your explanations

- `depth: junior` → explain the purpose of each module, key patterns, and common gotchas in plain language
- `depth: senior` → focus on architecture tradeoffs, coupling metrics, and blast radius; skip obvious patterns

## Using the structured data

| Field | How to use it |
|-------|--------------|
| `lobe_reading_order` | Present modules in this order; explain each before the next |
| `entry_points` | "Execution starts here" — explain these first |
| `hotspots` | "Don't touch these until you understand them" |
| `safe_zones` | "Start your first PR here" |
| `things_to_know` | Surface these warnings prominently |

## Focus mode

When a developer asks about a specific area:
```
cerebrofy_onboard(focus_lobe="auth", depth="senior")
```
This returns only the auth lobe and its immediate neighbours.
