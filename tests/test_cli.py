from click.testing import CliRunner

from skilldeck.cli import cli


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
