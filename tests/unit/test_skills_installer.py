"""Unit tests for cerebrofy.skills.installer."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebrofy.skills.installer import (
    AI_SKILL_ROOTS,
    SUPPORTED_AI_CLIENTS,
    install_skills,
    installed_skills,
)


def _seed_templates(templates_dir: Path, skill_names: list[str]) -> None:
    """Create fake SKILL.md templates under templates_dir."""
    for name in skill_names:
        skill_dir = templates_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name} skill\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# AI_SKILL_ROOTS / SUPPORTED_AI_CLIENTS
# ---------------------------------------------------------------------------


def test_supported_clients_not_empty() -> None:
    assert len(SUPPORTED_AI_CLIENTS) > 0


def test_ai_skill_roots_keys_match_supported_clients() -> None:
    assert set(AI_SKILL_ROOTS.keys()) == set(SUPPORTED_AI_CLIENTS)


# ---------------------------------------------------------------------------
# install_skills
# ---------------------------------------------------------------------------


def test_install_skills_raises_for_unknown_client(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported AI client"):
        install_skills(tmp_path, "invalid_client")


def test_install_skills_warns_when_templates_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", tmp_path / "nonexistent")
    warnings = install_skills(tmp_path, "copilot")
    assert any("templates" in w.lower() for w in warnings)


def test_install_skills_warns_when_no_skill_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    empty_templates = tmp_path / "templates"
    empty_templates.mkdir()
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", empty_templates)
    warnings = install_skills(tmp_path, "copilot")
    assert any("No skill" in w for w in warnings)


def test_install_skills_copies_skill_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    templates = tmp_path / "templates"
    _seed_templates(templates, ["my-skill"])
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", templates)

    repo = tmp_path / "repo"
    repo.mkdir()
    warnings = install_skills(repo, "copilot")
    dest = repo / ".copilot" / "skills" / "my-skill" / "SKILL.md"
    assert dest.exists()
    assert "# my-skill skill" in dest.read_text()
    assert warnings == []


def test_install_skills_skips_existing_without_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    templates = tmp_path / "templates"
    _seed_templates(templates, ["tool"])
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", templates)

    repo = tmp_path / "repo"
    repo.mkdir()
    install_skills(repo, "copilot")  # First install

    # Modify the installed file to verify it's NOT overwritten
    dest = repo / ".copilot" / "skills" / "tool" / "SKILL.md"
    dest.write_text("CUSTOM CONTENT\n", encoding="utf-8")
    warnings = install_skills(repo, "copilot")  # Second install without --force
    assert dest.read_text() == "CUSTOM CONTENT\n"
    assert len(warnings) > 0


def test_install_skills_overwrites_with_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    templates = tmp_path / "templates"
    _seed_templates(templates, ["tool"])
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", templates)

    repo = tmp_path / "repo"
    repo.mkdir()
    install_skills(repo, "copilot")

    dest = repo / ".copilot" / "skills" / "tool" / "SKILL.md"
    dest.write_text("CUSTOM CONTENT\n", encoding="utf-8")
    install_skills(repo, "copilot", force=True)  # Force overwrite
    assert "# tool skill" in dest.read_text()


def test_install_skills_warns_for_missing_skill_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    templates = tmp_path / "templates"
    # Create skill dir without SKILL.md
    (templates / "broken-skill").mkdir(parents=True)
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", templates)

    repo = tmp_path / "repo"
    repo.mkdir()
    warnings = install_skills(repo, "copilot")
    assert any("broken-skill" in w for w in warnings)


def test_install_skills_supports_all_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    templates = tmp_path / "templates"
    _seed_templates(templates, ["sk"])
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", templates)

    repo = tmp_path / "repo"
    repo.mkdir()
    for client in SUPPORTED_AI_CLIENTS:
        install_skills(repo, client)
        dest_root = repo / AI_SKILL_ROOTS[client] / "skills"
        assert dest_root.is_dir()


# ---------------------------------------------------------------------------
# installed_skills
# ---------------------------------------------------------------------------


def test_installed_skills_returns_empty_when_nothing_installed(tmp_path: Path) -> None:
    result = installed_skills(tmp_path, "copilot")
    assert result == []


def test_installed_skills_returns_paths_after_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cerebrofy.skills import installer as _mod
    templates = tmp_path / "templates"
    _seed_templates(templates, ["skill-a", "skill-b"])
    monkeypatch.setattr(_mod, "_TEMPLATES_DIR", templates)

    repo = tmp_path / "repo"
    repo.mkdir()
    install_skills(repo, "claude")
    paths = installed_skills(repo, "claude")
    assert len(paths) == 2
    assert all(p.name == "SKILL.md" for p in paths)


def test_installed_skills_returns_empty_for_unknown_client(tmp_path: Path) -> None:
    result = installed_skills(tmp_path, "unknown_client")
    assert result == []
