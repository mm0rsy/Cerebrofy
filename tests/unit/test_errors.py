"""Unit tests for the cerebrofy.errors hierarchy."""

from __future__ import annotations

import pytest

from cerebrofy.errors import (
    CerebrofyError,
    ConfigError,
    IntegrityError,
    InvalidRepoRootError,
    NeuronNotFoundError,
    NoActiveSessionError,
    NoIndexError,
    RecordingDisabledError,
    RootOutsideBoundaryError,
    SessionNotFoundError,
)

_ALL_SUBCLASSES: tuple[type[CerebrofyError], str] = (
    (ConfigError, "CONFIG_ERROR"),
    (NoIndexError, "NO_INDEX"),
    (SessionNotFoundError, "SESSION_NOT_FOUND"),
    (NoActiveSessionError, "NO_ACTIVE_SESSION"),
    (RecordingDisabledError, "RECORDING_DISABLED"),
    (NeuronNotFoundError, "NEURON_NOT_FOUND"),
    (InvalidRepoRootError, "INVALID_REPO_ROOT"),
    (RootOutsideBoundaryError, "ROOT_OUTSIDE_BOUNDARY"),
    (IntegrityError, "INTEGRITY_ERROR"),
)


# ---------------------------------------------------------------------------
# CerebrofyError base behaviour
# ---------------------------------------------------------------------------


def test_default_code_is_generic() -> None:
    err = CerebrofyError("something broke")
    assert err.code == "CEREBROFY_ERROR"
    assert isinstance(err, Exception)


def test_str_returns_plain_message_without_brackets() -> None:
    err = CerebrofyError("disk full")
    assert str(err) == "disk full"
    assert "[" not in str(err)
    assert "CEREBROFY_ERROR" not in str(err)


def test_explicit_code_override() -> None:
    err = CerebrofyError("nope", code="CUSTOM_CODE")
    assert err.code == "CUSTOM_CODE"
    assert str(err) == "nope"
    # Omitting code keeps the class default.
    assert CerebrofyError("nope").code == "CEREBROFY_ERROR"


# ---------------------------------------------------------------------------
# Subclasses carry their fixed codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    _ALL_SUBCLASSES,
    ids=lambda val: val if isinstance(val, str) else None,
)
def test_subclass_fixed_code(exc: type[CerebrofyError], expected_code: str) -> None:
    err = exc("oops")
    assert err.code == expected_code
    assert isinstance(err, CerebrofyError)
    assert str(err) == "oops"


def test_subclass_is_config_error_is_cerebrofy_error() -> None:
    assert issubclass(ConfigError, CerebrofyError)
    assert issubclass(IntegrityError, CerebrofyError)


def test_base_is_not_a_subclass_of_any_named_subclass() -> None:
    # The generic base must not masquerade as a specific subclass.
    assert not isinstance(CerebrofyError("x"), ConfigError)
    assert not isinstance(CerebrofyError("x"), IntegrityError)
