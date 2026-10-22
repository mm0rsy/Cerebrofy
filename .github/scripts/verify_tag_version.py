"""Assert the release tag matches the version the package reports.

The release pipeline no longer re-runs the test suite, so this is the check
that the tag it is about to publish actually corresponds to the built code.
Reads GITHUB_REF_NAME (e.g. ``v3.9.0``).
"""

from __future__ import annotations

import os
import sys

from cerebrofy import __version__


def verify() -> list[str]:
    tag = os.environ.get("GITHUB_REF_NAME", "").removeprefix("v")
    if not tag:
        return ["GITHUB_REF_NAME is not set; cannot verify the tag"]
    if tag != __version__:
        return [f"tag {tag} != packaged version {__version__}"]
    print(f"tag and packaged version agree: {tag}")
    return []


if __name__ == "__main__":
    errors = verify()
    for error in errors:
        print(error, file=sys.stderr)
    raise SystemExit(1 if errors else 0)
