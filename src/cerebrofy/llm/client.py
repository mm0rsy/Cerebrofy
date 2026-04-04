"""LLM client: openai SDK wrapper with streaming, retry, and wall-clock timeout."""

from __future__ import annotations

import sys
import threading
from typing import Any

import openai
import openai.types.chat

from cerebrofy.llm.prompt_builder import LLMContextPayload


class LLMClient:
    """OpenAI-compatible LLM client with retry and timeout."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int) -> None:
        self.model = model
        self.timeout = timeout
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)

    def _call_once(self, system_message: str, user_message: str) -> Any:
        """Send a single chat completion request; returns a Stream or full string."""
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            stream=True,
        )
        if isinstance(response, openai.types.chat.ChatCompletion):
            print(
                "Note: streaming not supported by endpoint, buffering response.",
                file=sys.stderr,
            )
            return response.choices[0].message.content or ""
        return response

    def call(self, payload: LLMContextPayload) -> str:
        """Call the LLM with retry (once on 5xx/connection error) and wall-clock timeout."""
        def _attempt() -> Any:
            try:
                return self._call_once(payload.system_message, payload.user_message)
            except openai.RateLimitError:
                raise
            except openai.BadRequestError:
                raise
            except (openai.APIStatusError, openai.APIConnectionError) as exc:
                reason = (
                    f"HTTP {exc.status_code}"
                    if isinstance(exc, openai.APIStatusError)
                    else "connection error"
                )
                print(
                    f"Cerebrofy: LLM request failed ({reason}), retrying...",
                    file=sys.stderr,
                )
                return self._call_once(payload.system_message, payload.user_message)

        stream_or_str = _attempt()

        if isinstance(stream_or_str, str):
            return stream_or_str

        timed_out = threading.Event()
        timer = threading.Timer(self.timeout, timed_out.set)
        timer.start()
        try:
            collected: list[str] = []
            for chunk in stream_or_str:
                if timed_out.is_set():
                    raise TimeoutError(
                        f"LLM request timed out after {self.timeout}s. "
                        "Increase llm_timeout in config.yaml or retry."
                    )
                token = chunk.choices[0].delta.content or ""
                collected.append(token)
                print(token, end="", flush=True)
            return "".join(collected)
        finally:
            timer.cancel()
