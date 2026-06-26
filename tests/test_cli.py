import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck.cli import cli, main
from skilldeck.registry import Skill, discover_skills


def test_list_includes_bundled_skill():
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "security-review" in result.output


def test_list_groups_by_category():
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
    # category headers are emitted, and each skill is listed under its header
    assert "security:" in result.output
    assert "review:" in result.output
    assert result.output.index("security:") < result.output.index("security-review")


def test_install_writes_file(tmp_path, monkeypatch):
    # project scope resolves against cwd, so run from a temp dir
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli, ["install", "security-review", "--agent", "claude"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude/skills/security-review/SKILL.md").is_file()


def test_install_requires_name_or_all():
    result = CliRunner().invoke(cli, ["install", "--agent", "claude"])
    assert result.exit_code != 0
    assert "specify skill name" in result.output


def test_install_all_writes_every_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["install", "--all", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    expected = {s.name for s in discover_skills()}
    skills_root = tmp_path / ".claude/skills"
    assert {p.name for p in skills_root.iterdir()} == expected
    assert all((skills_root / name / "SKILL.md").is_file() for name in expected)


def test_install_skips_agent_that_does_not_support_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    codex_only = Skill(
        name="codexonly",
        description="d",
        category="c",
        version="1",
        supported_agents=("codex",),
        body="B",
        path=Path("/nowhere"),
    )
    monkeypatch.setattr("skilldeck.cli.discover_skills", lambda **kw: [codex_only])
    result = CliRunner().invoke(cli, ["install", "codexonly", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    assert "skip codexonly: not supported by claude" in result.output
    assert not (tmp_path / ".claude/skills/codexonly/SKILL.md").exists()


def test_uninstall_removes_installed_skill(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "security-review", "--agent", "claude"])
    result = runner.invoke(cli, ["uninstall", "security-review", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    assert "removed security-review" in result.output
    assert not (tmp_path / ".claude/skills/security-review/SKILL.md").exists()


def test_uninstall_reports_when_not_installed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli, ["uninstall", "security-review", "--agent", "claude"]
    )
    assert result.exit_code == 0
    assert "not installed: security-review" in result.output


def test_main_reports_skill_error_cleanly(monkeypatch):
    # main() wraps cli() and turns a SkillError into a clean message, not a
    # traceback. An unknown skill name raises SkillError out of the command.
    monkeypatch.setattr(
        sys, "argv", ["skilldeck", "install", "does-not-exist", "--agent", "claude"]
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert "error: unknown skill: does-not-exist" in str(excinfo.value)
