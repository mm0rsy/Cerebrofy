---
agent: agent
description: Show the full blast radius of a code change — callers, test coverage gaps, and risk score
---

Compute the blast radius for the following target:

$ARGUMENTS

Steps:
1. Call `cerebrofy_blast_radius` with the target above. If no target is given, ask the user for a function name, file::name, or file:line.
2. Report the risk label (LOW / MEDIUM / HIGH) and explain what drives it (caller count, lobe spread, test coverage).
3. List `uncovered_callers` — these are the highest regression risk and should be reviewed or tested before merging.
4. If `runtime_boundary_callers` is non-empty, warn that those callers cross a process/framework boundary and require manual verification.
5. If the user wants a GitHub PR comment, run: `cerebrofy blast-radius <target> --output markdown` and show the result.

Do NOT open source files to find callers — the blast radius tool already has the complete call graph.
