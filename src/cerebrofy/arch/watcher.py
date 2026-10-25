"""Live architecture monitor loop with optional Slack alerting."""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

import rich_click as click


@dataclass(frozen=True)
class WatchSample:
    """One polling tick of the watch loop."""

    state: str  # caller-defined fingerprint; equality decides a redraw
    text: str  # terminal render for this tick
    alert_text: str | None  # Slack payload for this tick (None = no alert)


def watch_forever(
    sample: Callable[[], WatchSample],
    *,
    interval: float = 2.0,
    clear: bool = True,
    on_state_change: Callable[[str], None] | None = None,
) -> None:
    """Poll `sample` on an interval, clearing + redrawing when the state changes.

    on_state_change receives alert_text whenever a tick produces one and the
    state differs from the previous tick (except the very first). Raises
    KeyboardInterrupt out of the loop for the caller to handle.
    """
    previous: str | None = None
    while True:
        tick = sample()
        if tick.state != previous:
            if clear:
                click.clear()
            click.echo(tick.text)
            if on_state_change is not None and tick.alert_text is not None:
                on_state_change(tick.alert_text)
            previous = tick.state
        time.sleep(interval)


def send_slack(webhook: str, message: str) -> str | None:
    """POST {"text": message} to a Slack incoming webhook.

    Returns None on success or an error description. Payloads carry rule names
    and counts only — never source code.
    """
    try:
        request = urllib.request.Request(
            webhook,
            data=json.dumps({"text": message}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10):
            return None
    except Exception as exc:  # noqa: BLE001
        return str(exc) or exc.__class__.__name__
