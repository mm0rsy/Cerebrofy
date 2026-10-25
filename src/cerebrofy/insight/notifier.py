"""Insight notifier — emits insights to CLI, MCP, and optional webhooks."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cerebrofy.insight.daemon import Insight


def format_insights_cli(insights: list[Insight]) -> str:
    """Format insights for CLI display."""
    if not insights:
        return "No new insights."

    lines: list[str] = ["[bold]New Insights[/bold]\n"]
    for i, insight in enumerate(insights, 1):
        lines.append(f"[cyan]{i}. {insight.type}[/cyan] — {insight.title}")
        lines.append(f"   Confidence: {insight.confidence:.0%}")
        lines.append(f"   {insight.body}")
        if insight.recommendation:
            lines.append(f"   [dim]→ {insight.recommendation}[/dim]")
        if insight.affected_lobes:
            lines.append(f"   Lobes: {', '.join(insight.affected_lobes)}")
        lines.append("")
    return "\n".join(lines)


def format_insights_mcp(insights: list[dict[str, Any]], total: int, last_daemon_run: int) -> dict[str, Any]:
    """Format insights for MCP tool response."""
    return {
        "insights": [
            {
                "id": f"insight-{i}",
                "type": insight.get("type", "insight"),
                "title": insight.get("title", ""),
                "body": insight.get("body", ""),
                "confidence": insight.get("confidence", 0.7),
                "affected_neurons": insight.get("affected_neurons", []),
                "affected_lobes": insight.get("affected_lobes", []),
                "created_ts": insight.get("created_ts", 0),
                "recommendation": insight.get("recommendation", ""),
            }
            for i, insight in enumerate(insights)
        ],
        "total": total,
        "last_daemon_run": last_daemon_run,
    }


def maybe_send_webhook(insights: list[Insight]) -> None:
    """Send insights to configured webhook (Slack, etc.)."""
    webhook_url = os.getenv("CEREBROFY_WEBHOOK_URL")
    if not webhook_url or not insights:
        return

    import urllib.request

    payload: dict[str, Any] = {
        "text": f"Cerebrofy Insight Daemon: {len(insights)} new insight(s)",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Cerebrofy Insight Daemon*: {len(insights)} new insight(s)"},
            }
        ],
    }

    for insight in insights:
        payload["blocks"].append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{insight.type}*: {insight.title}\n{insight.body}\n*Recommendation*: {insight.recommendation}",
                },
            }
        )

    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pass  # Webhook failures are non-fatal