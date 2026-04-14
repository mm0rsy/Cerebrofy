"""Unit tests for cerebrofy.llm.client — retry and timeout behavior."""

from __future__ import annotations

import builtins
import importlib
import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest

from cerebrofy.llm.client import LLMClient
from cerebrofy.llm.prompt_builder import LLMContextPayload


def _make_payload() -> LLMContextPayload:
    return LLMContextPayload(
        system_message="system",
        user_message="user",
        lobe_names=(),
        token_estimate=10,
    )


def _require_openai() -> Any:
    return pytest.importorskip("openai")


def _make_client(timeout: int = 30) -> LLMClient:
    client = LLMClient.__new__(LLMClient)
    client._openai = _require_openai()
    client.model = "gpt-test"
    client.timeout = timeout
    client._client = MagicMock()
    return client


def test_llm_client_module_import_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the module should not require the optional openai package."""
    module_name = "cerebrofy.llm.client"
    sys.modules.pop(module_name, None)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "openai":
            raise ModuleNotFoundError("No module named 'openai'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    module = importlib.import_module(module_name)

    assert module.LLMClient.__name__ == "LLMClient"


def test_llm_client_raises_clear_error_when_openai_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing the client without openai should raise a clear Click error."""
    llm_client_module = importlib.import_module("cerebrofy.llm.client")

    def fake_import_module(name: str):
        if name == "openai":
            raise ModuleNotFoundError("No module named 'openai'")
        return importlib.import_module(name)

    monkeypatch.setattr(llm_client_module, "import_module", fake_import_module)

    with pytest.raises(click.ClickException, match="optional 'openai' extra"):
        llm_client_module.LLMClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-test",
            timeout=5,
        )


# ---------------------------------------------------------------------------
# T042: Retry behavior
# ---------------------------------------------------------------------------


def test_call_retries_on_500_error(capsys) -> None:
    """5xx APIStatusError on first call → retries once → success."""
    openai = _require_openai()
    client = _make_client()
    payload = _make_payload()

    # Mock _call_once: fail first, succeed second with non-streaming string
    error = openai.APIStatusError(
        "Server error",
        response=MagicMock(status_code=500),
        body={},
    )
    call_count = 0

    def fake_call_once(sys_msg: str, usr_msg: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise error
        return "success"

    with patch.object(client, "_call_once", side_effect=fake_call_once):
        result = client.call(payload)

    assert result == "success"
    assert call_count == 2
    captured = capsys.readouterr()
    assert "retrying" in captured.err


def test_call_no_retry_on_rate_limit() -> None:
    """429 RateLimitError → no retry, error propagates immediately."""
    openai = _require_openai()
    client = _make_client()
    payload = _make_payload()

    call_count = 0

    def fake_call_once(sys_msg: str, usr_msg: str) -> str:
        nonlocal call_count
        call_count += 1
        raise openai.RateLimitError(
            "Rate limit", response=MagicMock(status_code=429), body={}
        )

    with patch.object(client, "_call_once", side_effect=fake_call_once):
        with pytest.raises(openai.RateLimitError):
            client.call(payload)

    assert call_count == 1  # no retry


def test_call_no_retry_on_bad_request() -> None:
    """400 BadRequestError → no retry, error propagates immediately."""
    openai = _require_openai()
    client = _make_client()
    payload = _make_payload()

    call_count = 0

    def fake_call_once(sys_msg: str, usr_msg: str) -> str:
        nonlocal call_count
        call_count += 1
        raise openai.BadRequestError(
            "Bad request", response=MagicMock(status_code=400), body={}
        )

    with patch.object(client, "_call_once", side_effect=fake_call_once):
        with pytest.raises(openai.BadRequestError):
            client.call(payload)

    assert call_count == 1


def test_call_connection_error_retries(capsys) -> None:
    """APIConnectionError → retries once."""
    openai = _require_openai()
    client = _make_client()
    payload = _make_payload()

    call_count = 0

    def fake_call_once(sys_msg: str, usr_msg: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise openai.APIConnectionError(request=MagicMock())
        return "ok"

    with patch.object(client, "_call_once", side_effect=fake_call_once):
        result = client.call(payload)

    assert result == "ok"
    assert call_count == 2
    captured = capsys.readouterr()
    assert "retrying" in captured.err


# ---------------------------------------------------------------------------
# T043: Timeout behavior
# ---------------------------------------------------------------------------


def test_call_timeout_raises(capsys) -> None:
    """Wall-clock timeout fires before stream completes → TimeoutError raised."""
    client = _make_client(timeout=1)
    payload = _make_payload()

    def slow_stream(sys_msg: str, usr_msg: str):
        # Yield one token then pause for 3s (longer than timeout)
        def _gen():
            chunk = MagicMock()
            chunk.choices[0].delta.content = "hi"
            yield chunk
            time.sleep(3)
            chunk2 = MagicMock()
            chunk2.choices[0].delta.content = " world"
            yield chunk2
        return _gen()

    with patch.object(client, "_call_once", side_effect=slow_stream):
        with pytest.raises(TimeoutError, match="timed out"):
            client.call(payload)
