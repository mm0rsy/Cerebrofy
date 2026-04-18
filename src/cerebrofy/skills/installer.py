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
