"""GitHub PR comment integration via gh CLI.

Requires `gh` to be installed and authenticated.
"""

from __future__ import annotations

import subprocess
import sys


def post_pr_comment(pr_number: int, body: str, repo: str | None = None) -> tuple[bool, str]:
    """Post body as a comment on the given PR using the gh CLI.

    Returns (success, output_or_error).
    """
    cmd = ["gh", "pr", "comment", str(pr_number), "--body", body]
    if repo:
        cmd += ["--repo", repo]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "gh CLI not found. Install it from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return False, "gh CLI timed out after 30 seconds."


def get_pr_diff(pr_number: int, repo: str | None = None) -> tuple[bool, str]:
    """Fetch the unified diff for a PR using the gh CLI.

    Returns (success, diff_text_or_error).
    """
    cmd = ["gh", "pr", "diff", str(pr_number), "--patch"]
    if repo:
        cmd += ["--repo", repo]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "gh CLI not found. Install it from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return False, "gh CLI timed out after 30 seconds."


def parse_changed_files_from_diff(diff_text: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path not in files:
                files.append(path)
    return files
