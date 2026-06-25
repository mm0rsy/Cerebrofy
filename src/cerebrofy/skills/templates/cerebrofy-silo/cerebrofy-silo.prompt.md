Detect knowledge silos in this codebase — functions with high blast radius owned by few contributors.

Use the `cerebrofy_silo` MCP tool to get the full report. Then:

1. Identify CRITICAL and HIGH silos (silo_score ≥ 8)
2. For each, use `cerebrofy_impact` to confirm blast radius
3. Summarise the top 5 risks as: function name, primary owner, caller count, risk level
4. Recommend knowledge-transfer actions for each CRITICAL silo

If asked "what breaks if [person] leaves?", call `cerebrofy_silo` with `author` set to their email.
