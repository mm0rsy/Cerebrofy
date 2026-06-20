---
agent: agent
description: Build the optimal context window for a coding task — graph-aware, budget-constrained
---

Build the optimal context window for the following task:

$ARGUMENTS

Steps:
1. Call `cerebrofy_context` with the task above. Use `budget=8000` unless the user specifies otherwise.
2. For each neuron in the response:
   - If `inclusion_tier` is `full_source` or `signature_only`, use the `content` field directly — do NOT re-read the file.
   - If `inclusion_tier` is `lobe_summary`, use it for orientation only.
   - If `inclusion_tier` is `name_only`, note the location for reference.
3. Report `epistemic.caveats` if non-empty — warn the user if the index is stale.
4. Proceed with the task using only the returned context. Do not open additional files unless a specific path was returned by the optimizer AND you need to edit that exact location.
