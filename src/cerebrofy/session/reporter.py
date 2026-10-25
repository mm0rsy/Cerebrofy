"""Markdown + HTML report renderer for session replays (Idea #11).

Both renders are pure string builders — no external assets, no network — so the
HTML export is a single self-contained file and generation is far inside the
< 3 s acceptance target.
"""

from __future__ import annotations

import datetime
import html
from typing import Any

from cerebrofy.session.recorder import SessionEvent, SessionRecord
from cerebrofy.session.replay import SessionDiff, neuron_label

_OUTCOME_BADGE = {
    "success": "🟢 success",
    "partial": "🟡 partial",
    "failed": "🔴 failed",
    "unknown": "⚪ unknown",
}

_VERDICT_TEXT = {
    "increased": "⚠️ increased",
    "decreased": "🟢 decreased",
    "unchanged": "🟢 unchanged",
    "unknown": "⚪ unknown",
}


def format_utc(ts: int | None) -> str:
    """Format an epoch timestamp as ``YYYY-MM-DD HH:MM:SS UTC`` (— when None)."""
    if ts is None:
        return "—"
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


_utc = format_utc


def format_duration(seconds: int) -> str:
    """Human-readable duration, e.g. ``2m 15s``."""
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _event_details(event: SessionEvent, *, max_chars: int = 120) -> str:
    parts = [f"{key}={value}" for key, value in event.args.items() if value not in (None, "")]
    joined = " ".join(parts)
    if len(joined) > max_chars:
        return joined[:max_chars] + "…"
    return joined


def _metric(value: int | None) -> str:
    return "—" if value is None else str(value)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def render_markdown(
    session: SessionRecord,
    events: list[SessionEvent],
    diff: SessionDiff | None = None,
) -> str:
    """Render the full session replay as Markdown."""
    lines: list[str] = [
        f"# Session Replay — `{session.id}`",
        "",
        f"**Task:** {session.task}  ",
        f"**Agent:** {session.agent or 'unknown'}  ",
        f"**Started:** {_utc(session.started_at)}  ",
        f"**Ended:** {_utc(session.ended_at)}"
        + (f" ({format_duration(session.duration_seconds)})" if session.ended_at else " (running)"),
        "  ",
        f"**Outcome:** {_OUTCOME_BADGE.get(session.outcome, session.outcome)}  ",
        f"**Events recorded:** {session.event_count}  ",
        f"**Neurons touched:** {len(session.neurons_touched)}",
    ]
    if session.outcome_notes:
        lines += ["", f"> {session.outcome_notes}"]

    lines += ["", "## Risk Assessment", ""]
    lines += [
        "| Metric | Value |",
        "|---|---|",
        f"| Blast radius before | {_metric(session.blast_radius_before)} |",
        f"| Blast radius after | {_metric(session.blast_radius_after)} |",
        f"| Verdict | {_VERDICT_TEXT.get(diff.risk_verdict if diff else 'unknown', 'unknown')} |",
    ]

    if diff is not None:
        lines += ["", "## Graph Diff", ""]
        lines.append(
            f"- **Touched**: {len(diff.touched)} neuron(s)"
            + (f" — {', '.join(f'`{neuron_label(n)}`' for n in diff.touched[:10])}" if diff.touched else "")
        )
        if diff.missing:
            lines.append(
                f"- **No longer in index**: {', '.join(f'`{neuron_label(n)}`' for n in diff.missing)}"
            )
        if diff.appeared:
            lines.append(
                f"- **Appeared during session**: "
                f"{', '.join(f'`{neuron_label(n)}`' for n in diff.appeared)}"
            )
        if diff.graph_refreshed:
            lines.append("- **Index refreshed mid-session** (`cerebrofy build`/`update` was called)")

    lines += ["", "## Timeline", ""]
    if not events:
        lines.append("_No events recorded._")
    else:
        lines += ["| # | Time | Tool | Details | Result |", "|---|---|---|---|---|"]
        for i, event in enumerate(events, 1):
            details = _event_details(event).replace("|", "\\|")
            summary = (event.result_summary or "").replace("|", "\\|")
            if len(summary) > 120:
                summary = summary[:120] + "…"
            lines.append(
                f"| {i} | {_utc(event.ts)} | `{event.tool}` | {details} | {summary} |"
            )

    lines += [
        "",
        "---",
        "",
        "_Recorded locally by Cerebrofy — no code or session data leaves this machine._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# Default self-contained stylesheet for HTML export. Hoisted to a named module
# constant (m9 readability): the rendered HTML embeds it byte-for-byte, so this
# value is treated as output and covered by render_html's tests.
DEFAULT_HTML_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
     max-width:960px;margin:0 auto;padding:2rem;color:#24292e;line-height:1.6}
h1{border-bottom:2px solid #e1e4e8;padding-bottom:.5rem}
h2{border-bottom:1px solid #e1e4e8;padding-bottom:.3rem;color:#0366d6;margin-top:2rem}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #e1e4e8;padding:.5rem .75rem;text-align:left;vertical-align:top}
th{background:#f6f8fa;font-weight:600}
tr:nth-child(even){background:#f6f8fa}
code{background:#f6f8fa;padding:.1em .4em;border-radius:3px;
     font-family:"SFMono-Regular",Consolas,monospace;font-size:.9em}
.meta{display:flex;flex-wrap:wrap;gap:.5rem 2rem;margin:1rem 0}
.meta div{min-width:16rem}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;
       background:#f6f8fa;border:1px solid #e1e4e8;font-weight:600}
.cards{display:flex;flex-wrap:wrap;gap:1rem;margin:1rem 0}
.card{border:1px solid #e1e4e8;border-radius:6px;padding:.75rem 1rem;min-width:9rem}
.card .value{font-size:1.6rem;font-weight:700}
.card .label{color:#6a737d;font-size:.85rem}
.notes{background:#fffbdd;border-left:4px solid #f9c513;padding:.6rem 1rem;border-radius:4px}
footer{margin-top:2rem;color:#6a737d;font-size:.85rem}
"""


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_html(
    session: SessionRecord,
    events: list[SessionEvent],
    diff: SessionDiff | None = None,
) -> str:
    """Render a self-contained HTML replay page (no external assets)."""
    verdict_key = diff.risk_verdict if diff else "unknown"
    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Session Replay — {_esc(session.id)}</title>",
        f"<style>{DEFAULT_HTML_CSS}</style>",
        "</head>",
        "<body>",
        f"<h1>Session Replay — <code>{_esc(session.id)}</code></h1>",
        "<div class='meta'>",
        f"<div><strong>Task:</strong> {_esc(session.task)}</div>",
        f"<div><strong>Agent:</strong> {_esc(session.agent or 'unknown')}</div>",
        f"<div><strong>Started:</strong> {_esc(_utc(session.started_at))}</div>",
        "<div><strong>Ended:</strong> "
        + _esc(_utc(session.ended_at))
        + (
            f" ({_esc(format_duration(session.duration_seconds))})"
            if session.ended_at
            else " (running)"
        )
        + "</div>",
        "</div>",
        f"<p><span class='badge'>{_esc(_OUTCOME_BADGE.get(session.outcome, session.outcome))}</span></p>",
    ]
    if session.outcome_notes:
        parts.append(f"<div class='notes'>{_esc(session.outcome_notes)}</div>")

    parts += [
        "<h2>Risk Assessment</h2>",
        "<div class='cards'>",
        (f"<div class='card'><div class='value'>{_esc(_metric(session.blast_radius_before))}</div>"
        f"<div class='label'>Blast radius before</div></div>"),
        (f"<div class='card'><div class='value'>{_esc(_metric(session.blast_radius_after))}</div>"
        f"<div class='label'>Blast radius after</div></div>"),
        (f"<div class='card'><div class='value'>{_esc(_VERDICT_TEXT.get(verdict_key, 'unknown'))}</div>"
        f"<div class='label'>Verdict</div></div>"),
        (f"<div class='card'><div class='value'>{_esc(session.event_count)}</div>"
        f"<div class='label'>Events recorded</div></div>"),
        "</div>",
    ]

    if diff is not None:
        parts.append("<h2>Graph Diff</h2><ul>")
        parts.append(
            f"<li><strong>Touched:</strong> {len(diff.touched)} neuron(s)"
            + (
                " — "
                + ", ".join(f"<code>{_esc(neuron_label(n))}</code>" for n in diff.touched[:10])
                if diff.touched
                else ""
            )
            + "</li>"
        )
        if diff.missing:
            parts.append(
                "<li><strong>No longer in index:</strong> "
                + ", ".join(f"<code>{_esc(neuron_label(n))}</code>" for n in diff.missing)
                + "</li>"
            )
        if diff.appeared:
            parts.append(
                "<li><strong>Appeared during session:</strong> "
                + ", ".join(f"<code>{_esc(neuron_label(n))}</code>" for n in diff.appeared)
                + "</li>"
            )
        if diff.graph_refreshed:
            parts.append(
                "<li><strong>Index refreshed mid-session</strong> "
                "(<code>cerebrofy build</code>/<code>update</code> was called)</li>"
            )
        parts.append("</ul>")

    parts.append("<h2>Timeline</h2>")
    if not events:
        parts.append("<p><em>No events recorded.</em></p>")
    else:
        parts += [
            ("<table><thead><tr>"
            "<th>#</th><th>Time</th><th>Tool</th><th>Details</th><th>Result</th>"
            "</tr></thead><tbody>")
        ]
        for i, event in enumerate(events, 1):
            parts.append(
                f"<tr><td>{i}</td><td>{_esc(_utc(event.ts))}</td>"
                f"<td><code>{_esc(event.tool)}</code></td>"
                f"<td>{_esc(_event_details(event))}</td>"
                f"<td>{_esc(event.result_summary or '')}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts += [
        ("<footer>Recorded locally by Cerebrofy — no code or session data leaves "
        "this machine. Opt-in via <code>record_sessions: true</code> in "
        "<code>.cerebrofy/config.yaml</code>.</footer>"),
        "</body>",
        "</html>",
    ]
    return "\n".join(parts) + "\n"
