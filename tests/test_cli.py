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


def test_install_over_modified_file_fails_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "security-review", "--agent", "claude"])
    dest = tmp_path / ".claude/skills/security-review/SKILL.md"
    dest.write_text(dest.read_text() + "my tweak\n")

    result = runner.invoke(cli, ["install", "security-review", "--agent", "claude"])
    assert result.exit_code == 1
    assert "local modifications" in result.output
    assert "my tweak" in dest.read_text()

    result = runner.invoke(
        cli, ["install", "security-review", "--agent", "claude", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert "my tweak" not in dest.read_text()


def test_status_reports_each_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        cli, ["install", "security-review", "test-review", "--agent", "claude"]
    )
    dest = tmp_path / ".claude/skills/test-review/SKILL.md"
    dest.write_text(dest.read_text() + "my tweak\n")

    result = runner.invoke(cli, ["status", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    lines = {
        line.split()[0]: line for line in result.output.splitlines() if line.strip()
    }
    assert "up to date" in lines["security-review"]
    assert "modified locally" in lines["test-review"]
    assert "not installed" in lines["logging"]


def test_status_reports_orphans(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orphan = tmp_path / ".claude/skills/retired-skill/SKILL.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("left behind\n")
    result = CliRunner().invoke(cli, ["status", "--agent", "claude"])
    assert result.exit_code == 0
    assert "orphan:" in result.output
    assert "retired-skill" in result.output


def test_update_refreshes_stale_and_skips_modified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        cli, ["install", "security-review", "test-review", "--agent", "claude"]
    )
    stale = tmp_path / ".claude/skills/security-review/SKILL.md"
    # simulate an install from an older skilldeck: rewrite with an old stamp
    from skilldeck.stamp import stamp

    stale.write_text(stamp("old body\n", "security-review", "0.0.1"))
    modified = tmp_path / ".claude/skills/test-review/SKILL.md"
    modified.write_text(modified.read_text() + "my tweak\n")

    result = runner.invoke(cli, ["update", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    assert "updated security-review (0.0.1 ->" in result.output
    assert "skip test-review: locally modified" in result.output
    assert "old body" not in stale.read_text()
    assert "my tweak" in modified.read_text()

    # --force also refreshes the modified install
    result = runner.invoke(cli, ["update", "--agent", "claude", "--force"])
    assert result.exit_code == 0, result.output
    assert "my tweak" not in modified.read_text()


def test_update_with_nothing_installed_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["update", "--agent", "claude"])
    assert result.exit_code == 0
    assert "nothing to update" in result.output


def test_main_reports_skill_error_cleanly(monkeypatch):
    # main() wraps cli() and turns a SkillError into a clean message, not a
    # traceback. An unknown skill name raises SkillError out of the command.
    monkeypatch.setattr(
        sys, "argv", ["skilldeck", "install", "does-not-exist", "--agent", "claude"]
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert "error: unknown skill: does-not-exist" in str(excinfo.value)
