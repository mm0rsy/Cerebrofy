"""Rich terminal output, sparklines, history tables, and JSON export for health metrics."""

from __future__ import annotations

import datetime
import json
from typing import Any

from cerebrofy.health.metrics import HealthMetrics

# Unicode block characters for sparklines (index 0 = space/lowest)
_BLOCKS = " ▁▂▃▄▅▆▇█"


def _delta_str(curr: float, prev: float | None, higher_is_better: bool) -> str:
    if prev is None:
        return "—"
    d = curr - prev
    if abs(d) < 0.001:
        arrow, badge = "→", "—"
    elif d > 0:
        arrow = "↑"
        badge = "✅" if higher_is_better else "⚠️"
    else:
        arrow = "↓"
        badge = "⚠️" if higher_is_better else "✅"
    return f"{arrow} {d:+.2f}  {badge}"


def format_health_snapshot(
    metrics: HealthMetrics,
    prev: dict[str, Any] | None = None,
    ts: int | None = None,
    commit: str | None = None,
) -> str:
    """Return a rich terminal string showing current metrics + delta from prev snapshot."""
    now_str = (
        datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "now"
    )
    lines = [f"\n🧠 Cerebrofy Health — {now_str}\n"]
    if commit:
        lines.append(f"  Commit: {commit}\n")

    def row(label: str, val: float, unit: str, hib: bool, key: str) -> str:
        pval = prev.get(key) if prev else None
        return f"  {label:<22} {val:>8.2f}{unit}  {_delta_str(val, pval, hib)}"

    lines.append(row("Coupling Score", metrics.coupling, "  ", False, "coupling"))
    lines.append(row("Avg Blast Radius", metrics.avg_blast, "  ", False, "avg_blast"))
    lines.append(row("Dead Code %", metrics.dead_code_pct, "% ", False, "dead_code_pct"))
    lines.append(row("Lobe Cohesion", metrics.cohesion, "  ", True, "cohesion"))
    lines.append(row("Test Surface", metrics.test_surface, "% ", True, "test_surface"))
    lines.append(row("Drift Velocity", metrics.drift_velocity, "/d", False, "drift_velocity"))
    lines.append(row("Hub Concentration", metrics.hub_concentration, "% ", False, "hub_concentration"))
    lines.append("")
    lines.append(f"  Neurons: {metrics.neuron_count:,}   Edges: {metrics.edge_count:,}")

    if metrics.hotspots:
        lines.append("\n  Complexity Hotspots (top 10 by caller_count × lobe_spread):")
        for i, h in enumerate(metrics.hotspots, 1):
            lines.append(
                f"  {i:2}. {h['name']}  ({h['file']})"
                f"  — {h['caller_count']} callers × {h['lobe_spread']} lobes = {h['score']}"
            )

    return "\n".join(lines) + "\n"


def format_history_table(snapshots: list[dict[str, Any]]) -> str:
    """Return a plain-text table of historical health snapshots."""
    if not snapshots:
        return "No health snapshots found. Run 'cerebrofy build' first.\n"

    col_fmt = (
        f"{'#':>3}  {'Date':<16}  {'Commit':<8}  "
        f"{'Coupling':>8}  {'AvgBlast':>8}  {'DeadCode%':>9}  "
        f"{'Cohesion':>8}  {'TestSurf%':>9}  {'HubConc%':>8}  "
        f"{'Neurons':>7}  {'Edges':>7}"
    )
    rows = [col_fmt, "─" * len(col_fmt)]
    for i, s in enumerate(snapshots, 1):
        dt = datetime.datetime.fromtimestamp(s["build_ts"]).strftime("%Y-%m-%d %H:%M")
        commit = (s.get("commit_hash") or "")[:8]
        rows.append(
            f"{i:>3}  {dt:<16}  {commit:<8}  "
            f"{(s.get('coupling') or 0):>8.3f}  "
            f"{(s.get('avg_blast') or 0):>8.1f}  "
            f"{(s.get('dead_code_pct') or 0):>9.1f}  "
            f"{(s.get('cohesion') or 0):>8.3f}  "
            f"{(s.get('test_surface') or 0):>9.1f}  "
            f"{(s.get('hub_concentration') or 0):>8.1f}  "
            f"{(s.get('neuron_count') or 0):>7,}  "
            f"{(s.get('edge_count') or 0):>7,}"
        )
    return "\n".join(rows) + "\n"


def format_trend_sparkline(snapshots: list[dict[str, Any]], metric: str) -> str:
    """Return an ASCII sparkline for *metric* across the given snapshots (oldest → newest)."""
    if not snapshots:
        return "No data.\n"
    values = [float(s.get(metric) or 0) for s in reversed(snapshots)]
    min_v, max_v = min(values), max(values)
    if max_v == min_v:
        spark = "─" * len(values)
    else:
        spark = "".join(
            _BLOCKS[int((v - min_v) / (max_v - min_v) * 8)] for v in values
        )
    return f"\n  {metric}:  {spark}\n  min={min_v:.3f}  max={max_v:.3f}  builds={len(values)}\n"


def to_export_json(
    metrics: HealthMetrics,
    prev: dict[str, Any] | None = None,
    ts: int | None = None,
    commit: str | None = None,
) -> str:
    """Serialize current metrics + delta + trend to JSON (matches MCP output schema)."""
    delta: dict[str, float] = {}
    trend: dict[str, str] = {}
    metric_keys = (
        "coupling", "avg_blast", "dead_code_pct", "cohesion",
        "test_surface", "drift_velocity", "hub_concentration",
    )
    if prev:
        for key in metric_keys:
            curr_val = getattr(metrics, key)
            prev_val = prev.get(key)
            if prev_val is not None:
                d = curr_val - prev_val
                delta[key] = round(d, 4)
                trend[key] = "up" if d > 0.001 else ("down" if d < -0.001 else "stable")

    return json.dumps(
        {
            "build_ts": ts,
            "commit": commit,
            "current": {
                "coupling": metrics.coupling,
                "avg_blast": metrics.avg_blast,
                "dead_code_pct": metrics.dead_code_pct,
                "cohesion": metrics.cohesion,
                "test_surface": metrics.test_surface,
                "drift_velocity": metrics.drift_velocity,
                "hub_concentration": metrics.hub_concentration,
                "neuron_count": metrics.neuron_count,
                "edge_count": metrics.edge_count,
            },
            "delta": delta,
            "trend": trend,
            "summary": format_health_snapshot(metrics, prev, ts, commit),
            "hotspots": list(metrics.hotspots),
        },
        indent=2,
    )
