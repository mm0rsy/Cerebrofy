# Skill: cerebrofy-health

> Longitudinal, graph-derived codebase health — know whether your codebase is getting better or worse on every build.

## ⚠️ Navigation rule

**Call `cerebrofy_health` before any architectural discussion or refactor decision.**

This gives you graph-derived metrics no text tool can compute: blast radius trends,
lobe coupling, dead code drift, and hub concentration — all evolving over time.

## When to use

- Before a sprint retro: check if health improved or degraded.
- Before a refactor: establish the baseline coupling and cohesion scores.
- When a PR looks risky: check drift velocity and hub concentration trend.
- Any time you want to know whether the codebase architecture is getting better or worse.

## MCP tool

```
cerebrofy_health()
cerebrofy_health(since_build=5, metric="coupling")
cerebrofy_health(since_build=1, format="json")
```

## CLI commands

```bash
cerebrofy health                         # current snapshot + delta from last build
cerebrofy health --history 30            # last 30 builds as a table
cerebrofy health --trend coupling        # ASCII sparkline for coupling over time
cerebrofy health --export json           # JSON export of current snapshot
```

## Metrics explained

| Metric | Direction | Definition |
|--------|-----------|-----------|
| Coupling Score | ↓ better | Cross-lobe edge ratio (0–1) |
| Avg Blast Radius | ↓ better | Mean depth-2 caller count per neuron |
| Dead Code % | ↓ better | Neurons with zero in/out edges (excl. entry points) |
| Lobe Cohesion | ↑ better | Mean intra-lobe edge ratio per lobe (0–1) |
| Test Surface | ↑ better | % non-test neurons reachable from test entry points |
| Drift Velocity | ↓ better | Structural neuron changes per day (rolling 7-day) |
| Hub Concentration | ↓ better | % edges touching top-5% degree nodes |

## Output example

```
🧠 Cerebrofy Health — 2026-06-21 02:00

  Coupling Score          0.23  ↓ -0.04  ✅
  Avg Blast Radius       12.40  ↑ +1.10  ⚠️
  Dead Code %             4.10% ↓ -0.80  ✅
  Lobe Cohesion           0.71  → +0.00  —
  Test Surface           81.00% ↑ +3.00  ✅
  Drift Velocity          2.10/d ↑ +0.40 ⚠️
  Hub Concentration      18.00% ↑ +2.00  ⚠️

  Neurons: 1,204   Edges: 3,891
```
