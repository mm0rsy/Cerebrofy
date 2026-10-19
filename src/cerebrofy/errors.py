"""Cerebrofy error hierarchy (shared foundation for Wave A).

Dependency-free — importing this module pulls in no Cerebrofy code, so it can
be used from config parsing, planning, indexing and session surfaces without
risking import cycles.

The base :class:`CerebrofyError` carries a stable, machine-readable ``code``
attribute. Each named subclass pins a fixed ``code``; callers may still override
per-instance via the ``code=`` keyword of the base constructor. ``__str__``
returns the plain message only (no bracketed prefix).
"""

from __future__ import annotations


class CerebrofyError(Exception):
    """Base error for all Cerebrofy failures.

    Attributes:
        code: Stable machine-readable error code. Defaults to a generic class
            attribute; subclasses set a fixed value and callers may override
            it per-instance.
        message: The human-readable message returned by :meth:`__str__`.
    """

    code: str = "CEREBROFY_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def __str__(self) -> str:
        return self.message


class ConfigError(CerebrofyError):
    """Malformed or invalid ``.cerebrofy/config.yaml`` or section content."""

    code: str = "CONFIG_ERROR"


class NoIndexError(CerebrofyError):
    """A query or command was issued against a missing `cerebrofy.db` index."""

    code: str = "NO_INDEX"


class SessionNotFoundError(CerebrofyError):
    """A specific session id could not be found."""

    code: str = "SESSION_NOT_FOUND"


class NoActiveSessionError(CerebrofyError):
    """A command requires an active session but none is recorded."""

    code: str = "NO_ACTIVE_SESSION"


class RecordingDisabledError(CerebrofyError):
    """Session recording was requested but is disabled."""

    code: str = "RECORDING_DISABLED"


class NeuronNotFoundError(CerebrofyError):
    """A neuron lookup by id/name/file:line failed."""

    code: str = "NEURON_NOT_FOUND"


class InvalidRepoRootError(CerebrofyError):
    """A path supplied as the repo root is not a valid Cerebrofy repo."""

    code: str = "INVALID_REPO_ROOT"


class RootOutsideBoundaryError(CerebrofyError):
    """The resolved repo root escapes the indexed boundary."""

    code: str = "ROOT_OUTSIDE_BOUNDARY"


class IntegrityError(CerebrofyError):
    """A database integrity check (``PRAGMA integrity_check``) reported failure."""

    code: str = "INTEGRITY_ERROR"
