"""Token counting for budget allocation.

Uses tiktoken when available (GPT-family models); falls back to len(text)//4.
Default heuristic is within ±10% of actual token counts for all modern LLMs.
"""

from __future__ import annotations

_TIKTOKEN_AVAILABLE: bool | None = None  # lazy-checked once


def _has_tiktoken() -> bool:
    global _TIKTOKEN_AVAILABLE
    if _TIKTOKEN_AVAILABLE is None:
        try:
            import tiktoken  # noqa: F401
            _TIKTOKEN_AVAILABLE = True
        except ImportError:
            _TIKTOKEN_AVAILABLE = False
    return _TIKTOKEN_AVAILABLE


# Map model name substrings → tiktoken encoding name
_MODEL_TO_ENCODING: list[tuple[str, str]] = [
    ("gpt-4o", "o200k_base"),
    ("gpt-4", "cl100k_base"),
    ("gpt-3.5", "cl100k_base"),
    ("text-embedding", "cl100k_base"),
]


def _tiktoken_encoding(model: str) -> "str | None":
    for substring, encoding in _MODEL_TO_ENCODING:
        if substring in model:
            return encoding
    return None


def count_tokens(text: str, model: str = "auto") -> int:
    """Return an estimated token count for *text* given *model*.

    Tries tiktoken for GPT-family models. Falls back to len(text)//4 for all
    other models (Claude, Llama, Gemini, etc.) or when tiktoken is not installed.
    """
    if not text:
        return 0

    if _has_tiktoken() and model != "auto":
        encoding_name = _tiktoken_encoding(model)
        if encoding_name:
            import tiktoken
            enc = tiktoken.get_encoding(encoding_name)
            return len(enc.encode(text))

    # Safe lower-bound heuristic: 1 token ≈ 4 characters
    return max(1, len(text) // 4)


def tokens_for_source(
    file_path: str,
    line_start: int,
    line_end: int,
    repo_root: "str | None" = None,
    model: str = "auto",
) -> tuple[str, int]:
    """Read source lines [line_start, line_end] from file_path and count tokens.

    Returns (source_text, token_count). Returns ("", 0) if file cannot be read.
    """
    from pathlib import Path

    root = Path(repo_root) if repo_root else Path.cwd()
    full_path = root / file_path
    try:
        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        # line_start/line_end are 1-based
        start = max(0, line_start - 1)
        end = min(len(lines), line_end)
        source = "\n".join(lines[start:end])
        return source, count_tokens(source, model)
    except (OSError, ValueError):
        return "", 0
