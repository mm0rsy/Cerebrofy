You are using Cerebrofy's epistemic confidence layer.

Run: cerebrofy_epistemic() or `cerebrofy epistemic`

This tells you how much to trust the current index:
- overall_confidence (0.5–1.0): composite score
- graph_age_hours: how old the index is
- neurons_changed_since_build: files modified since last build
- unindexed_languages: code that cerebrofy can't see
- dynamic_dispatch_count: neurons that may hide callers
- caveats: human-readable warnings
- recommendation: what to do next

If confidence < 0.7, run `cerebrofy update` or `cerebrofy build` before proceeding.

Note: every other Cerebrofy MCP tool response also includes an "epistemic" field automatically.
