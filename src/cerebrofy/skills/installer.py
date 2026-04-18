"""AI skill installer — copies bundled SKILL.md templates into .<ai>/skills/ at init time."""

from __future__ import annotations

import shutil
from pathlib import Path

# Map of --ai flag value → destination root directory (relative to repo root).
AI_SKILL_ROOTS: dict[str, str] = {
    "copilot": ".copilot",
    "claude": ".claude",
    "opencode": ".opencode",
    "vscode": ".vscode",
}

# AI clients that also support .github/prompts/ slash commands.
AI_PROMPT_CLIENTS: set[str] = {"copilot"}

# Map of --ai flag value → (prompt dest dir, prompt file suffix).
# Only clients whose slash-command convention is known are listed.
AI_PROMPT_DIRS: dict[str, tuple[str, str]] = {
    "copilot":  (".github/prompts",   ".prompt.md"),
    "vscode":   (".github/prompts",   ".prompt.md"),
    "claude":   (".claude/commands",  ".md"),
    "opencode": (".opencode/commands", ".md"),
}

# Global instructions file per AI client (relative to repo root).
# These files are read automatically by the AI on EVERY interaction — ideal for
# "always use the index, never glob-read source files" rules.
AI_INSTRUCTIONS_FILES: dict[str, str] = {
    "copilot":  ".github/copilot-instructions.md",
    "vscode":   ".github/copilot-instructions.md",
    "claude":   "CLAUDE.md",
    "opencode": ".opencode/instructions.md",
}

# Marker tags used to fence the cerebrofy-managed block inside instructions files.
# Using HTML comments so they're invisible in rendered Markdown.
_MARKER_START = "<!-- cerebrofy:start -->"
_MARKER_END   = "<!-- cerebrofy:end -->"

_INSTRUCTIONS_BLOCK = """\
<!-- cerebrofy:start -->
## Codebase Navigation — Cerebrofy Index

This project's codebase is indexed by [Cerebrofy](https://github.com/mm0rsy/Cerebrofy).
The semantic index lives at `.cerebrofy/db/cerebrofy.db`.

**Navigation rules (enforced):**

1. **NEVER glob-read or recursively open source files** to understand the codebase.
   The index already contains every function, class, and module with embeddings.

2. **ALWAYS start with a cerebrofy query** when asked about code structure or behaviour:
   ```bash
   cerebrofy search "<your question in plain English>"
   ```

3. Use the pre-built summaries for orientation — no parsing needed:
   - `.cerebrofy/cerebrofy_map.md` — full codebase map
   - `.cerebrofy/lobes/<name>_lobe.md` — per-module summaries

4. **Only open a specific source file** after cerebrofy has returned its file path and
   line number — and only to read or edit *that exact location*.

5. If the Cerebrofy MCP server is running, prefer the MCP tools (`search_code`,
   `get_neuron`, `list_lobes`) over the CLI — they return structured results directly.
<!-- cerebrofy:end -->
"""

# All supported --ai values.
SUPPORTED_AI_CLIENTS = list(AI_SKILL_ROOTS.keys())

# Directory inside the package that holds skill template subdirectories.
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def install_skills(root: Path, ai_client: str, force: bool = False) -> list[str]:
    """Copy all SKILL.md templates into <root>/.<ai>/skills/<skill-name>/SKILL.md.

    Returns a list of warning strings (non-fatal issues).
    """
    if ai_client not in AI_SKILL_ROOTS:
        raise ValueError(
            f"Unsupported AI client '{ai_client}'. "
            f"Choose from: {', '.join(SUPPORTED_AI_CLIENTS)}"
        )

    dest_root = root / AI_SKILL_ROOTS[ai_client] / "skills"
    warnings: list[str] = []

    if not _TEMPLATES_DIR.is_dir():
        warnings.append(
            f"Warning: Skill templates directory not found at {_TEMPLATES_DIR}. "
            "Skipping skill installation."
        )
        return warnings

    skill_dirs = sorted(d for d in _TEMPLATES_DIR.iterdir() if d.is_dir())
    if not skill_dirs:
        warnings.append("Warning: No skill templates found. Skipping skill installation.")
        return warnings

    dest_root.mkdir(parents=True, exist_ok=True)

    for skill_dir in skill_dirs:
        src_skill = skill_dir / "SKILL.md"
        if not src_skill.exists():
            warnings.append(
                f"Warning: {skill_dir.name}/SKILL.md not found — skipping."
            )
            continue

        dest_skill_dir = dest_root / skill_dir.name
        dest_skill_dir.mkdir(parents=True, exist_ok=True)
        dest_skill = dest_skill_dir / "SKILL.md"

        if dest_skill.exists() and not force:
            warnings.append(
                f"Cerebrofy: {dest_skill} already exists — skipping (use --force to overwrite)."
            )
            continue

        shutil.copy2(src_skill, dest_skill)

        # Install slash-command prompt files for clients that support them.
        if ai_client in AI_PROMPT_DIRS:
            prompts_subdir, suffix = AI_PROMPT_DIRS[ai_client]
            for prompt_src in skill_dir.glob("*.prompt.md"):
                prompts_dir = root / prompts_subdir
                prompts_dir.mkdir(parents=True, exist_ok=True)
                # Rewrite the filename extension to match the client's convention.
                stem = prompt_src.stem.removesuffix(".prompt")  # e.g. cerebrofy-build
                prompt_dest = prompts_dir / (stem + suffix)
                if prompt_dest.exists() and not force:
                    warnings.append(
                        f"Cerebrofy: {prompt_dest} already exists — skipping (use --force to overwrite)."
                    )
                    continue
                shutil.copy2(prompt_src, prompt_dest)

    return warnings


def installed_skills(root: Path, ai_client: str) -> list[Path]:
    """Return list of SKILL.md paths already installed for the given AI client."""
    if ai_client not in AI_SKILL_ROOTS:
        return []
    dest_root = root / AI_SKILL_ROOTS[ai_client] / "skills"
    if not dest_root.is_dir():
        return []
    return sorted(dest_root.glob("*/SKILL.md"))


def install_instructions(root: Path, ai_client: str, force: bool = False) -> str | None:
    """Write (or update) the cerebrofy navigation rules block into the AI client's
    global instructions file (e.g. `.github/copilot-instructions.md`, `CLAUDE.md`).

    The block is fenced between ``<!-- cerebrofy:start -->`` / ``<!-- cerebrofy:end -->``
    markers so subsequent calls are idempotent — the block is replaced, not appended.

    Returns the destination path as a string, or ``None`` if the client is not supported.
    """
    if ai_client not in AI_INSTRUCTIONS_FILES:
        return None

    dest = root / AI_INSTRUCTIONS_FILES[ai_client]
    dest.parent.mkdir(parents=True, exist_ok=True)

    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""

    if _MARKER_START in existing and _MARKER_END in existing:
        if not force:
            # Block already present — check if it's already up to date.
            start = existing.index(_MARKER_START)
            end   = existing.index(_MARKER_END) + len(_MARKER_END)
            current_block = existing[start:end]
            if current_block.strip() == _INSTRUCTIONS_BLOCK.strip():
                return str(dest)  # nothing to do
        # Replace the existing block.
        start = existing.index(_MARKER_START)
        end   = existing.index(_MARKER_END) + len(_MARKER_END)
        updated = existing[:start].rstrip() + "\n\n" + _INSTRUCTIONS_BLOCK + existing[end:].lstrip()
    else:
        # Append the block (with a blank-line separator).
        separator = "\n\n" if existing.strip() else ""
        updated = existing + separator + _INSTRUCTIONS_BLOCK

    dest.write_text(updated, encoding="utf-8")
    return str(dest)
