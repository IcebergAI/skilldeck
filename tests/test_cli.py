import sys

import pytest
from click.testing import CliRunner

from skilldeck.cli import cli, main


def test_list_includes_bundled_skill():
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "security-review" in result.output


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
    installed = list((tmp_path / ".claude/skills").iterdir())
    assert len(installed) >= 2  # all bundled skills, not just one


def test_main_reports_skill_error_cleanly(monkeypatch):
    # main() wraps cli() and turns a SkillError into a clean message, not a
    # traceback. An unknown skill name raises SkillError out of the command.
    monkeypatch.setattr(
        sys, "argv", ["skilldeck", "install", "does-not-exist", "--agent", "claude"]
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert "error: unknown skill: does-not-exist" in str(excinfo.value)
