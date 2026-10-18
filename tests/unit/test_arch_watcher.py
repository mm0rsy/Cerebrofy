"""Unit tests for cerebrofy.arch.watcher — watch loop and Slack notifier."""

from __future__ import annotations

import json
from typing import Any

import pytest

from cerebrofy.arch.watcher import WatchSample, send_slack, watch_forever


class _LoopDone(Exception):
    """Raised by the stub clock to stop the watch loop."""


def test_watch_loop_redraws_on_state_change(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter(
        [
            WatchSample(state="PASS", text="clean", alert_text=None),
            WatchSample(state="PASS", text="clean", alert_text=None),  # no redraw
            WatchSample(state="FAIL", text="broken", alert_text="drift alert"),
            WatchSample(state="FAIL", text="broken", alert_text="drift alert 2"),
            WatchSample(state="WARN", text="warned", alert_text=None),  # redraw, no alert
        ]
    )
    echoes: list[str] = []
    alerts: list[str] = []
    sleeps: list[float] = []

    monkeypatch.setattr("cerebrofy.arch.watcher.click.clear", lambda: None)
    monkeypatch.setattr("cerebrofy.arch.watcher.click.echo", echoes.append)

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 5:
            raise _LoopDone

    monkeypatch.setattr("cerebrofy.arch.watcher.time.sleep", fake_sleep)

    with pytest.raises(_LoopDone):
        watch_forever(
            lambda: next(ticks), interval=2.0, clear=True, on_state_change=alerts.append
        )

    assert echoes == ["clean", "broken", "warned"]
    assert alerts == ["drift alert"]
    assert sleeps == [2.0, 2.0, 2.0, 2.0, 2.0]


def test_watch_loop_runs_without_alert_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    echoes: list[str] = []
    monkeypatch.setattr("cerebrofy.arch.watcher.click.echo", echoes.append)
    monkeypatch.setattr("cerebrofy.arch.watcher.click.clear", lambda: None)

    def fake_sleep(_seconds: float) -> None:
        raise _LoopDone

    monkeypatch.setattr("cerebrofy.arch.watcher.time.sleep", fake_sleep)

    def sample() -> WatchSample:
        return WatchSample(state="FAIL", text="broken", alert_text="ignored")

    with pytest.raises(_LoopDone):
        watch_forever(sample, interval=1.0, clear=False, on_state_change=None)

    assert echoes == ["broken"]


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_send_slack_posts_names_only_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeRequest:
        def __init__(self, url: str, data: bytes, headers: dict[str, str], method: str) -> None:
            captured.update({"url": url, "data": data, "headers": headers, "method": method})

    def fake_urlopen(request: FakeRequest, timeout: float) -> _FakeResponse:
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("cerebrofy.arch.watcher.urllib.request.Request", FakeRequest)
    monkeypatch.setattr("cerebrofy.arch.watcher.urllib.request.urlopen", fake_urlopen)

    assert send_slack("https://hooks.slack.com/services/X", "drift summary") is None
    assert captured["url"] == "https://hooks.slack.com/services/X"
    assert captured["method"] == "POST"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["timeout"] == 10
    assert json.loads(bytes(captured["data"]).decode()) == {"text": "drift summary"}


def test_send_slack_returns_error_string(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("network down")

    monkeypatch.setattr("cerebrofy.arch.watcher.urllib.request.urlopen", boom)
    error = send_slack("https://hooks.slack.com/services/X", "msg")
    assert error is not None
    assert "network down" in error
