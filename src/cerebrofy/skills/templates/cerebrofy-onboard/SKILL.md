````markdown
# Skill: cerebrofy-onboard

> Generate a topology-derived onboarding guide for any developer joining a codebase.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use

- At the start of any onboarding session ("help me understand this codebase")
- When asked "where should I start?" or "what should I read first?"
- Before making a large change — understand the hotspots and safe zones first

## How to use via MCP

```
cerebrofy_onboard()
cerebrofy_onboard(depth="junior")
cerebrofy_onboard(focus_lobe="auth", depth="senior")
cerebrofy_onboard(name="Alice", depth="junior")
```

The tool returns:
- `markdown` — full ONBOARDING.md content ready to present
- `structured.lobe_reading_order` — ordered list of modules with metrics
- `structured.entry_points` — where execution starts
- `structured.hotspots` — top-10 complexity hotspots (understand before touching)
- `structured.safe_zones` — low-risk modules (start contributing here)
- `structured.things_to_know` — warnings and decisions from the memory store

## How to use via CLI

```bash
cerebrofy onboard                       # generates .cerebrofy/ONBOARDING.md
cerebrofy onboard --name "Alice"        # personalised greeting
cerebrofy onboard --focus auth          # focus on the auth lobe
cerebrofy onboard --format html         # interactive HTML output
cerebrofy onboard --depth senior        # hint: skip basics
```

## Reading the output as an AI agent

The `depth` field in the output tells you how to calibrate:
- `junior` — explain each module's purpose and key patterns; include docstrings
- `senior` — focus on architecture, data flow, and coupling metrics; skip basics

## Quick reference

| Goal | MCP call |
|------|---------|
| Full onboarding guide | `cerebrofy_onboard()` |
| Focus on one module | `cerebrofy_onboard(focus_lobe="<lobe>")` |
| Senior-level guide | `cerebrofy_onboard(depth="senior")` |
| Where execution starts | `structured.entry_points` from any call |
| What to avoid first | `structured.hotspots` |
| Where to start contributing | `structured.safe_zones` |
````
