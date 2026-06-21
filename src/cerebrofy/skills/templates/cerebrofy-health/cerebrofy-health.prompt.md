You are using Cerebrofy's codebase health timeline.

Run: cerebrofy_health() or `cerebrofy health`

This gives you 7 graph-derived health metrics with delta from the previous build:
- Coupling Score (cross-lobe edge ratio — lower is better)
- Avg Blast Radius (mean depth-2 caller count — lower is better)
- Dead Code % (isolated neurons — lower is better)
- Lobe Cohesion (intra-lobe edge ratio — higher is better)
- Test Surface (% neurons reachable from tests — higher is better)
- Drift Velocity (structural changes/day rolling 7-day — lower is better)
- Hub Concentration (% edges on top-5% degree nodes — lower is better)

For historical trends: cerebrofy_health(since_build=10) or `cerebrofy health --history 30`
For a sparkline: `cerebrofy health --trend coupling`
