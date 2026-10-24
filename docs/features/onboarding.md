# Onboarding

`cerebrofy onboard` generates a personalized **onboarding guide** from the cerebrofy index — a topology-derived reading order, entry points, complexity hotspots, and safe zones for any developer joining the project.

## What It Is

When a new developer joins a project, they need to understand the codebase structure quickly. Cerebrofy's onboarding command generates a personalized guide that answers: where do I start, what should I read first, what's dangerous to touch, and where can I safely contribute?

## CLI Reference

```bash
cerebrofy onboard                          # generates .cerebrofy/ONBOARDING.md
cerebrofy onboard --name "Alice"           # personalized welcome header
cerebrofy onboard --focus auth             # restrict guide to the auth lobe
cerebrofy onboard --format html            # self-contained interactive HTML
cerebrofy onboard --depth senior           # skip basics, focus on architecture
cerebrofy onboard --output ~/ONBOARDING.md # write to a custom path
```

- `--name NAME` — personalized welcome header
- `--focus LOBE` — restrict guide to a specific lobe
- `--format FORMAT` — `markdown` (default) or `html` (self-contained interactive HTML)
- `--depth LEVEL` — `senior` (skip basics, focus on architecture) or default
- `--output PATH` — write to a custom path instead of `.cerebrofy/ONBOARDING.md`

## Guide Contents

| Section | Source |
|---------|--------|
| **Reading Order** | Topological sort of lobes by call-graph dependency |
| **Entry Points** | Neurons with `in_degree == 0 && out_degree > 0` (CLI commands, event handlers) |
| **Hotspots** | Top-10 functions by blast radius — understand these before touching them |
| **Safe Zones** | Lobes with low coupling and low blast radius — start contributing here |
| **Things to Know** | `warning` and `decision` memories attached to high-traffic neurons |

Output is written to `.cerebrofy/ONBOARDING.md` (or `.cerebrofy/ONBOARDING.html` with `--format html`). The HTML output is fully self-contained with zero external dependencies.

## Data Flow

1. Topological sort of lobes by call-graph dependency → reading order
2. Find neurons with `in_degree == 0 && out_degree > 0` → entry points
3. Compute blast radius for all neurons → top-10 hotspots
4. Compute coupling per lobe → safe zones (low coupling, low blast radius)
5. Query `warning` and `decision` memories → things to know

## Integration Points

- **Blast Radius** — hotspots are top-10 functions by blast radius
- **Memory** — warning/decision memories become "things to know"
- **Health** — coupling metrics determine safe zones

## Related

- [Blast Radius](./blast-radius.md) — hotspot identification
- [Memory](./memory.md) — warning/decision memories in the guide
- [Health](./health.md) — coupling metrics for safe zones