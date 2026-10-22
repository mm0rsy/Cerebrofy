"""Assert a built wheel ships everything the package needs at runtime.

Catches the failure mode that otherwise only shows up on a release tag: a
wheel that builds fine but is missing a non-Python asset (the upgrade
manifests are shipped via an explicit `include` in pyproject.toml) or the
console entry point.

Usage: python .github/scripts/verify_wheel.py [dist]
"""

from __future__ import annotations

import glob
import sys
import zipfile
from pathlib import Path

REQUIRED_PATHS = ("cerebrofy/__init__.py", "cerebrofy/cli.py")


def verify(dist_dir: str = "dist") -> list[str]:
    wheels = sorted(glob.glob(str(Path(dist_dir) / "*.whl")))
    if not wheels:
        return [f"no wheel found in {dist_dir}/"]

    wheel = wheels[0]
    names = zipfile.ZipFile(wheel).namelist()

    missing = [path for path in REQUIRED_PATHS if path not in names]
    if not any("upgrade/manifests/" in name for name in names):
        missing.append("cerebrofy/upgrade/manifests/*.yaml")
    if not any(name.endswith("METADATA") for name in names):
        missing.append("*.dist-info/METADATA")

    if missing:
        return [f"{wheel} is missing: {missing}"]

    print(f"{wheel}: {len(names)} files, all required assets present")
    return []


if __name__ == "__main__":
    errors = verify(sys.argv[1] if len(sys.argv) > 1 else "dist")
    for error in errors:
        print(error, file=sys.stderr)
    raise SystemExit(1 if errors else 0)
