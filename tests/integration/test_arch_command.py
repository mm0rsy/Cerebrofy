"""Integration tests for `cerebrofy arch` commands (check/explain/history/init)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main


class _FakeEmbedder:
    """Minimal Embedder stand-in so the build command runs without models."""

    @property
    def dim(self) -> int:
        return 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _setup_git_repo(tmp_path: Path) -> None:
    _git(["git", "init"], tmp_path)
    _git(["git", "config", "user.email", "test@cerebrofy.test"], tmp_path)
    _git(["git", "config", "user.name", "CerebrofyTest"], tmp_path)
    _git(["git", "remote", "add", "origin", "https://example.com/repo.git"], tmp_path)

    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "module.py").write_text(
        "def existing(x: int) -> int:\n    return x + 1\n\n"
        "def caller() -> int:\n    return existing(2)\n",
        encoding="utf-8",
    )

    _git(["git", "add", "."], tmp_path)
    _git(["git", "commit", "-m", "initial"], tmp_path)


def _build(runner: CliRunner) -> None:
    with patch("cerebrofy.commands.build.get_embedder", return_value=_FakeEmbedder()):
        result = runner.invoke(main, ["build"])
    assert result.exit_code == 0, f"build failed:\n{result.output}"


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repo with a cerebrofy index built from a calling pair of functions."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--no-mcp"])
    assert result.exit_code == 0, f"init failed:\n{result.output}"
    _build(runner)
    return tmp_path


# ---------------------------------------------------------------------------
# arch check — exit code contract
# ---------------------------------------------------------------------------


RULES_VIOLATED = """\
rules:
  - name: no-intra-lobe-calls
    severity: error
    check:
      no_edge:
        from_lobe: src
        to_lobe: src
"""


def _write_rules(root: Path, text: str) -> None:
    (root / ".cerebrofy" / "arch-rules.yaml").write_text(text, encoding="utf-8")


def test_check_violated_rule_exits_1_and_records_history(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 1, f"expected exit 1:\n{result.output}"
    assert "no-intra-lobe-calls" in result.output
    assert "existing" in result.output
    # history sidecar records the failing run (names and counts only)
    record = json.loads(
        (repo / ".cerebrofy" / "arch-history.jsonl").read_text(encoding="utf-8")
    )
    assert record["result"] == "FAIL"
    assert record["failing"] == [{"rule": "no-intra-lobe-calls", "severity": "error",
                                  "count": record["failing"][0]["count"]}]
    assert record["failing"][0]["count"] >= 1


def test_check_passing_rule_exits_0(repo: Path) -> None:
    _write_rules(
        repo,
        "rules:\n  - name: no-circular-lobe-deps\n    check: { no_cycles: { scope: lobes } }\n",
    )
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 0, f"expected exit 0:\n{result.output}"
    assert "RESULT: ✅ PASSED" in result.output


def test_check_warn_only_exits_0(repo: Path) -> None:
    _write_rules(
        repo,
        """\
rules:
  - name: noisy-caller
    severity: warning
    check:
      no_edge:
        from_lobe: src
        to_lobe: src
""",
    )
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "noisy-caller" in result.output


def test_check_missing_rules_file_exits_0_with_hint(repo: Path) -> None:
    (repo / ".cerebrofy" / "arch-rules.yaml").unlink()
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 0, f"missing rules must not block:\n{result.output}"
    assert "arch init" in result.output


def test_check_malformed_rules_exits_2(repo: Path) -> None:
    _write_rules(repo, "rules:\n  - name: x\n    check:\n      teleport: {}\n")
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 2, f"expected exit 2:\n{result.output}"
    assert "unknown check type" in result.output


def test_check_unknown_rule_name_exits_2(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check", "--rule", "nope"])
    assert result.exit_code == 2
    assert "rule 'nope' not found" in result.output


def test_check_unknown_lobe_reference_exits_2(repo: Path) -> None:
    _write_rules(
        repo,
        """\
rules:
  - name: typo-lobe
    severity: warning
    check:
      no_edge:
        from_lobe: ap
        to_lobe: src
""",
    )
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 2, f"expected exit 2:\n{result.output}"
    assert "unknown lobe(s) ap" in result.output


def test_check_exit_1_takes_precedence_over_config_errors(repo: Path) -> None:
    _write_rules(
        repo,
        """\
rules:
  - name: no-intra-lobe-calls
    severity: error
    check: { no_edge: { from_lobe: src, to_lobe: src } }
  - name: typo-lobe
    severity: warning
    check: { no_edge: { from_lobe: ap, to_lobe: src } }
""",
    )
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 1  # error-severity wins over the config error
    assert "typo-lobe" in result.output  # config error is still reported


# ---------------------------------------------------------------------------
# arch check — formats and since
# ---------------------------------------------------------------------------


def test_check_json_format_carries_spec_keys(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check", "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert {"rules_checked", "passing", "failing", "warnings", "result"} <= set(data)
    assert data["result"] == "FAIL"
    assert data["passing"] == []
    assert data["failing"][0]["rule"] == "no-intra-lobe-calls"
    location = data["failing"][0]["violations"][0]
    assert location["file"] == "src/module.py"
    assert location["line"] >= 1


def test_check_annotations_format(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check", "--format", "github-annotations"])
    assert result.exit_code == 1
    assert "::error file=src/module.py,line=" in result.output


def test_check_since_head_filters_all_violations(repo: Path) -> None:
    """A clean worktree means `git diff --name-only HEAD` finds nothing → PASS."""
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check", "--since", "HEAD"])
    assert result.exit_code == 0, f"expected filtered pass:\n{result.output}"


def test_check_since_touched_file_still_reports(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    # --no-verify: v4 hooks always block commits while rules are violated;
    # the anchor commit only needs to exist for `--since HEAD` diffing.
    _git(["git", "commit", "--allow-empty", "--no-verify", "-m", "anchor"], repo)
    # actually modify the file so `git diff --name-only HEAD` reports it
    (repo / "src" / "module.py").write_text(
        "def existing(x: int) -> int:\n    return x + 1\n\n"
        "def caller() -> int:\n    return existing(2)\n\n# touched\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["arch", "check", "--since", "HEAD"])
    assert result.exit_code == 1, result.output


def test_check_since_bad_ref_exits_2(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check", "--since", "bogus-ref-42"])
    assert result.exit_code == 2, result.output
    assert "could not diff" in result.output


def test_check_supported_formats_only(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check", "--format", "html"])
    assert result.exit_code == 2  # click.Choice usage error


# ---------------------------------------------------------------------------
# arch explain
# ---------------------------------------------------------------------------


def test_explain_shows_definition(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "explain", "no-intra-lobe-calls"])
    # explain mirrors the check verdict — the violated rule exits 1
    assert result.exit_code == 1, result.output
    assert "Check: no_edge: 'src' must not call 'src'" in result.output
    assert "Fix hint:" in result.output
    assert "RULE VIOLATION: no-intra-lobe-calls" in result.output
    assert "Introduced in: commit" in result.output


def test_explain_passing_rule_exits_0(repo: Path) -> None:
    _write_rules(
        repo,
        "rules:\n  - name: no-circular-lobe-deps\n    check: { no_cycles: { scope: lobes } }\n",
    )
    result = CliRunner().invoke(main, ["arch", "explain", "no-circular-lobe-deps"])
    assert result.exit_code == 0, result.output
    assert "Check: no_cycles: scope=lobes" in result.output


def test_explain_unknown_rule_exits_2(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "explain", "ghost"])
    assert result.exit_code == 2
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# arch history
# ---------------------------------------------------------------------------


def test_history_hints_when_empty(repo: Path) -> None:
    result = CliRunner().invoke(main, ["arch", "history"])
    assert result.exit_code == 0, result.output
    assert "No arch check history yet" in result.output


def test_history_lists_runs_and_json(repo: Path) -> None:
    _write_rules(repo, RULES_VIOLATED)
    CliRunner().invoke(main, ["arch", "check"])
    CliRunner().invoke(main, ["arch", "check", "--format", "json"])

    text = CliRunner().invoke(main, ["arch", "history"])
    assert text.exit_code == 0
    assert "2 runs recorded" in text.output
    assert "no-intra-lobe-calls" in text.output

    as_json = CliRunner().invoke(main, ["arch", "history", "--json"])
    assert as_json.exit_code == 0
    entries = json.loads(as_json.output)
    assert len(entries) == 2
    assert entries[-1]["result"] == "FAIL"


def test_hook_flag_records_no_history(repo: Path) -> None:
    """--hook mode never writes history and skips the human header."""
    _write_rules(repo, RULES_VIOLATED)
    result = CliRunner().invoke(main, ["arch", "check", "--hook", "pre-commit"])
    assert result.exit_code == 1, result.output
    assert "🧠" not in result.output  # hook_mode: no banner
    assert not (repo / ".cerebrofy" / "arch-history.jsonl").exists()


def test_hook_mode_quiet_when_clean(repo: Path) -> None:
    _write_rules(repo, "rules:\n  - name: c\n    check: { no_cycles: { scope: lobes } }\n")
    result = CliRunner().invoke(main, ["arch", "check", "--hook", "pre-push"])
    assert result.exit_code == 0
    assert result.output.strip() == ""


# ---------------------------------------------------------------------------
# arch init
# ---------------------------------------------------------------------------


def test_init_scaffolds_and_wizard_adds_rule(repo: Path) -> None:
    rules_file = repo / ".cerebrofy" / "arch-rules.yaml"
    assert rules_file.exists()  # scaffolded by cerebrofy init

    # All-default wizard run: kind, from lobe, to lobe, severity, description, name
    result = CliRunner().invoke(main, ["arch", "init"], input="\n\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "Rule added" in result.output

    import yaml

    data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
    assert data["rules"][0]["name"] == "no-src-in-src"
    assert data["rules"][0]["check"]["no_edge"] == {"from_lobe": "src", "to_lobe": "src"}
    assert data["rules"][0]["severity"] == "warning"


def test_init_ci_writes_workflow(repo: Path) -> None:
    result = CliRunner().invoke(main, ["arch", "init", "--ci"])
    assert result.exit_code == 0, result.output
    workflow = repo / ".github" / "workflows" / "cerebrofy-arch.yml"
    assert workflow.exists()
    text = workflow.read_text(encoding="utf-8")
    assert "cerebrofy arch check" in text

    # no --force → refuses to overwrite; --force → overwrites
    again = CliRunner().invoke(main, ["arch", "init", "--ci"])
    assert again.exit_code == 0
    assert "already exists" in again.output
    forced = CliRunner().invoke(main, ["arch", "init", "--ci", "--force"])
    assert forced.exit_code == 0
    assert "already exists" not in forced.output


def test_arch_requires_cerebrofy_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running arch commands without cerebrofy init is a config error (exit 2)."""
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 2
    assert "cerebrofy init" in result.output


def test_check_missing_index_exits_0(repo: Path) -> None:
    """Skip semantics: no index → warn and exit 0 (matches validate)."""
    _write_rules(repo, RULES_VIOLATED)
    (repo / ".cerebrofy" / "db" / "cerebrofy.db").unlink()
    result = CliRunner().invoke(main, ["arch", "check"])
    assert result.exit_code == 0, result.output
    assert "no index" in result.output


# ---------------------------------------------------------------------------
# arch watch (single live tick, loop stopped via a stub clock)
# ---------------------------------------------------------------------------


class _StopLoop(Exception):
    """Raised by the stub clock to terminate the watch loop after one tick."""


def test_watch_one_tick_reports_and_alerts(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real watch sample() renders text and fires on_state_change on first fail."""
    _write_rules(repo, RULES_VIOLATED)
    alerts: list[str] = []
    monkeypatch.setattr("cerebrofy.commands.arch.send_slack", lambda hook, text: alerts.append(text))
    monkeypatch.setenv("CEREBROFY_SLACK_WEBHOOK", "https://hooks.slack.com/services/T/B/X")

    def fake_sleep(_seconds: float) -> None:
        raise _StopLoop

    monkeypatch.setattr("cerebrofy.arch.watcher.time.sleep", fake_sleep)
    monkeypatch.setattr("cerebrofy.arch.watcher.click.clear", lambda: None)

    result = CliRunner().invoke(
        main, ["arch", "watch", "--no-clear", "--interval", "0.1", "--slack"]
    )
    # the loop was stopped by the stub clock; CLI reports the non-zero stop
    assert result.exit_code != 0
    assert "no-intra-lobe-calls" in result.output
    assert "RESULT: ❌ FAILED" in result.output
    assert len(alerts) == 1  # first tick fires the alert callback (no prior state)
