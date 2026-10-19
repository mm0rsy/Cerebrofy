"""Argument / result truncation for the session recorder (Idea #11).

Redacts sensitive keys and bounds value lengths so no single coding hour can
write an unbounded blob into ``sessions.db``.  All functions here are pure
(no IO) and were hoisted from ``recorder.py`` (m9 maintainability split).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

# ── constants ────────────────────────────────────────────────────────────────

_MAX_ARG_VALUE_CHARS = 300
_MAX_ARG_ITEMS = 20

# Sensitive-key *patterns* redacted from stored arguments.  Matching is
# case-insensitive and substring-based (after normalizing separators) so keys
# like ``API-Key``, ``my_token`` or ``userAuthorization`` are caught even when
# nested inside argument dicts.  Bare ``auth`` is intentionally omitted: its
# substring would false-positive on legitimate keys such as ``author``.
_SENSITIVE_PATTERNS: tuple[str, ...] = tuple(sorted({
    "api_key", "apikey", "access_token", "refresh_token", "token", "secret",
    "password", "passwd", "pwd", "authorization", "client_secret",
    "private_key", "ssh_key", "cert", "credential", "bearer",
}))

# Normalize separators (``-``, ``_``, ``.``, whitespace) to ``_`` before matching
# so ``api-key`` / ``api.key`` line up with the ``api_key`` pattern.
_SEP_RE = re.compile(r"[-_.\s]+")

# Cap recursion so redaction can't be abused to walk a pathological structure.
_MAX_NESTING_DEPTH = 10


# ── helpers ──────────────────────────────────────────────────────────────────

def _normalize_key(key: str) -> str:
    """Lower-case *key* and collapse separators to ``_`` for pattern matching."""
    return _SEP_RE.sub("_", key).lower()


def _is_sensitive_key(key: Any) -> bool:
    """Case-insensitive substring match against sensitive-key patterns.

    Returns ``False`` for non-str keys so integers / ``None`` keys are never
    accidentally treated as sensitive.  Robust to separator variants
    (``api-key`` == ``api_key`` == ``apikey``).
    """
    if not isinstance(key, str):
        return False
    normalized = _normalize_key(key)
    return any(pattern in normalized for pattern in _SENSITIVE_PATTERNS)


def _truncate_leaf(value: Any, max_value_chars: int) -> Any:
    """Bound a scalar's length when it is a string; pass other types through."""
    if isinstance(value, str) and len(value) > max_value_chars:
        return value[:max_value_chars] + "…"
    return value


def _redact_structure(
    value: Any,
    *,
    max_value_chars: int,
    max_items: int,
    depth: int,
) -> Any:
    """Recursively redact sensitive keys and bound lengths, preserving types.

    Dict keys whose normalized form matches a sensitive pattern are replaced
    with ``"[REDACTED]"`` regardless of the (possibly nested) value type.  Lists
    and tuples are walked element-wise; mappings are reduced.  Recursion is
    capped by *depth* so deeply nested input can't drive unbounded work.
    Non-str keys/values are passed through untouched.
    """
    if depth <= 0:
        # Never pass nested containers through unredacted: a secret buried
        # deeper than the recursion cap would otherwise be persisted raw.
        if isinstance(value, (Mapping, list, tuple)):
            return "[MAX_DEPTH]"
        return _truncate_leaf(value, max_value_chars)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, val in list(value.items())[:max_items]:
            out[key] = (
                "[REDACTED]"
                if _is_sensitive_key(key)
                else _redact_structure(
                    val,
                    max_value_chars=max_value_chars,
                    max_items=max_items,
                    depth=depth - 1,
                )
            )
        return out
    if isinstance(value, (list, tuple)):
        factory = type(value)
        return factory(
            _redact_structure(
                v,
                max_value_chars=max_value_chars,
                max_items=max_items,
                depth=depth - 1,
            )
            for v in list(value)[:max_items]
        )
    return _truncate_leaf(value, max_value_chars)


# ── public API ───────────────────────────────────────────────────────────────

def truncate_args(
    args: Mapping[str, Any],
    *,
    max_value_chars: int = _MAX_ARG_VALUE_CHARS,
    max_items: int = _MAX_ARG_ITEMS,
) -> dict[str, Any]:
    """Copy *args*, redacting sensitive keys and truncating long values.

    Redaction is applied **recursively** before truncation/serialization:
    sensitive keys (``api_key``, ``access_token``, ``authorization``,
    ``client_secret``, ``password`` …) are replaced with ``"[REDACTED]"``
    even when nested inside dicts/lists/tuples, using case-insensitive
    pattern matching so variant spellings (``API-Key``, ``my_token``) are
    caught.  Non-str keys/values are passed through untouched; recursion is
    capped at :data:`_MAX_NESTING_DEPTH` to bound work on deep structures.
    """
    return cast(
        dict[str, Any],
        _redact_structure(
            args,
            max_value_chars=max_value_chars,
            max_items=max_items,
            depth=_MAX_NESTING_DEPTH,
        ),
    )


def truncate_summary(text: str | None, *, max_chars: int = 500) -> str | None:
    """Collapse whitespace and truncate a tool result summary."""
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) > max_chars:
        return collapsed[:max_chars] + "…"
    return collapsed
