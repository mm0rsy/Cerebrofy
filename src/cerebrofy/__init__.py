"""Cerebrofy — AI-powered codebase intelligence CLI."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("cerebrofy")
except PackageNotFoundError:
    __version__ = "unknown"
