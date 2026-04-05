"""LLM prompt builder: system prompt template + lobe context injection."""

from __future__ import annotations

import string
from dataclasses import dataclass

from cerebrofy.search.hybrid import HybridSearchResult

DEFAULT_SYSTEM_PROMPT = """\
You are a senior software architect with deep knowledge of the following codebase.

## Codebase Context (from Cerebrofy index)

$lobe_context

## Your Task

Generate a structured feature specification for the following feature request.
The spec must reference only real code units shown in the context above.
Format the output as Markdown with sections: Overview, Requirements, Acceptance Criteria.\
"""


@dataclass(frozen=True)
class LLMContextPayload:
    """Context payload passed to the LLM client."""

    system_message: str
    user_message: str
    lobe_names: tuple[str, ...]
    token_estimate: int


def _load_template(template_path: str | None, repo_root: str) -> string.Template:
    """Load a system prompt Template from a file, or return the built-in default."""
    if not template_path:
        return string.Template(DEFAULT_SYSTEM_PROMPT)
    from pathlib import Path
    resolved = Path(repo_root) / template_path
    if not resolved.exists():
        raise FileNotFoundError(f"system_prompt_template file not found: {resolved}")
    return string.Template(resolved.read_text(encoding="utf-8"))


def _build_lobe_context(lobe_files: dict[str, str]) -> str:
    """Concatenate lobe .md files into a single context string, sorted by lobe name."""
    if not lobe_files:
        return ""
    parts: list[str] = []
    for lobe_name in sorted(lobe_files.keys()):
        lobe_path = lobe_files[lobe_name]
        try:
            content = open(lobe_path, encoding="utf-8").read()
        except FileNotFoundError:
            continue
        parts.append(f"## {lobe_name}\n\n{content}\n\n")
    return "".join(parts)


def build_llm_context(
    result: HybridSearchResult,
    template_path: str | None,
    repo_root: str,
) -> LLMContextPayload:
    """Build the full LLM context payload from a HybridSearchResult."""
    tmpl = _load_template(template_path, repo_root)
    lobe_context = _build_lobe_context(result.affected_lobe_files)
    system_message = tmpl.safe_substitute(lobe_context=lobe_context)
    user_message = result.query
    lobe_names = tuple(sorted(result.affected_lobe_files.keys()))
    token_estimate = len(system_message) // 4
    return LLMContextPayload(
        system_message=system_message,
        user_message=user_message,
        lobe_names=lobe_names,
        token_estimate=token_estimate,
    )
