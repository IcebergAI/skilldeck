"""``skilldeck migrate`` and the ``status``/``update`` hints that point to it."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck.adapters import ADAPTERS, MIGRATIONS
from skilldeck.cli import cli
from skilldeck.registry import discover_skills
from skilldeck.stamp import parse
from skilldeck.targets import Scope

#: agent -> (old-format path, native path) of the ``logging`` skill at
#: project scope
MOVES = {
    "codex": (".codex/prompts/logging.md", ".agents/skills/logging/SKILL.md"),
    "copilot": (
        ".github/prompts/logging.prompt.md",
        ".github/skills/logging/SKILL.md",
    ),
    "cursor": (".cursor/rules/logging.mdc", ".cursor/skills/logging/SKILL.md"),
    "kiro": (".kiro/steering/logging.md", ".kiro/skills/logging/SKILL.md"),
}


def _skill(name):
    return next(s for s in discover_skills() if s.name == name)


def _install_old(agent, root, name="logging", scope=Scope.PROJECT):
    """Install ``name`` for ``agent`` the way skilldeck used to."""
    (source,) = MIGRATIONS[agent]
    return source.install(_skill(name), scope, project_root=root)


def _migrate(*args):
    return CliRunner().invoke(cli, ["migrate", *args])


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def test_every_agent_with_an_old_format_can_migrate():
    assert sorted(MIGRATIONS) == ["codex", "copilot", "cursor", "kiro"]
    for agent, (old, new) in MOVES.items():
        (source,) = MIGRATIONS[agent]
        assert source.relative_path(_skill("logging")) == Path(old)
        assert ADAPTERS[agent].relative_path(_skill("logging")) == Path(new)


@pytest.mark.parametrize("agent", sorted(MOVES))
def test_migrate_moves_a_stamped_install(project, agent):
    old, new = (project / p for p in MOVES[agent])
    _install_old(agent, project)
    other = _install_old(agent, project, "security-review")

    result = _migrate("--agent", agent)
    assert result.exit_code == 0, result.output
    assert f"migrated logging: {old} -> {new}" in result.output
    assert not old.exists() and not other.exists()
    assert ADAPTERS[agent].render(_skill("logging")) in new.read_text()
    found = parse(new.read_text())
    assert found is not None and not found.modified
    assert old.parent.is_dir()  # a shared directory, never removed

    status = CliRunner().invoke(cli, ["status", "--agent", agent])
    assert "up to date" in status.output.split("logging")[1].split("\n")[0]
    assert "hint" not in status.output


def test_migrate_is_idempotent(project):
    old, new = (project / p for p in MOVES["copilot"])
    _install_old("copilot", project)
    assert _migrate("--agent", "copilot").exit_code == 0
    migrated = new.read_text()

    result = _migrate("--agent", "copilot")
    assert result.exit_code == 0, result.output
    assert result.output == "nothing to migrate\n"
    assert new.read_text() == migrated and not old.exists()


def test_migrate_leaves_a_modified_install_unless_forced(project):
    old, new = (project / p for p in MOVES["cursor"])
    _install_old("cursor", project)
    old.write_text(old.read_text() + "my team's addition\n")

    result = _migrate("--agent", "cursor")
    assert result.exit_code == 0, result.output
    assert f"skip logging: {old} has local modifications; left in place" in (
        result.output
    )
    assert "my team's addition" in old.read_text()
    assert not new.exists()

    result = _migrate("--agent", "cursor", "--force")
    assert result.exit_code == 0, result.output
    assert "migrated logging" in result.output
    assert not old.exists()
    assert "my team's addition" not in new.read_text()


def test_migrate_leaves_an_unstamped_file_unless_forced(project):
    # skilldeck 0.3.0 and earlier didn't stamp its installs, but a file at the
    # old path may just as well be the user's own: #95 rules apply.
    old, new = (project / p for p in MOVES["codex"])
    old.parent.mkdir(parents=True)
    old.write_text("an unstamped prompt\n")

    result = _migrate("--agent", "codex")
    assert result.exit_code == 0, result.output
    assert f"skip logging: {old} has no skilldeck stamp" in result.output
    assert "skilldeck 0.3.0 or earlier" in result.output
    assert old.read_text() == "an unstamped prompt\n"
    assert not new.exists()

    result = _migrate("--agent", "codex", "--force")
    assert result.exit_code == 0, result.output
    assert not old.exists()
    assert parse(new.read_text()) is not None


def test_migrate_force_removes_a_symlink_but_not_its_target(project):
    old, new = (project / p for p in MOVES["kiro"])
    target = project / "shared/logging.md"
    target.parent.mkdir()
    target.write_text("shared steering\n")
    old.parent.mkdir(parents=True)
    old.symlink_to(target)

    result = _migrate("--agent", "kiro")
    assert result.exit_code == 0, result.output
    assert "is a symlink skilldeck did not create; left in place" in result.output
    assert old.is_symlink() and not new.exists()

    result = _migrate("--agent", "kiro", "--force")
    assert result.exit_code == 0, result.output
    assert not old.is_symlink() and new.is_file()
    assert target.read_text() == "shared steering\n"


def test_migrate_never_removes_a_directory(project):
    old, new = (project / p for p in MOVES["codex"])
    old.mkdir(parents=True)
    result = _migrate("--agent", "codex", "--force")
    assert result.exit_code == 0, result.output
    assert f"skip logging: {old} is a directory, which skilldeck never removes" in (
        result.output
    )
    assert old.is_dir() and not new.exists()


def test_migrate_keeps_the_old_file_if_the_new_location_is_taken(project):
    old, new = (project / p for p in MOVES["copilot"])
    CliRunner().invoke(cli, ["install", "logging", "--agent", "copilot"])
    new.write_text(new.read_text() + "edited\n")
    _install_old("copilot", project)

    result = _migrate("--agent", "copilot")
    assert result.exit_code == 1
    assert "error:" in result.output and "has local modifications" in result.output
    assert old.is_file()
    assert "edited" in new.read_text()

    result = _migrate("--agent", "copilot", "--force")
    assert result.exit_code == 0, result.output
    assert not old.exists()
    assert "edited" not in new.read_text()


def test_migrate_global_codex_prompts_whatever_codex_home_says(
    tmp_path, home, monkeypatch
):
    # skilldeck wrote Codex prompts under ~/.codex, ignoring CODEX_HOME, and
    # Codex reads ~/.agents/skills, which CODEX_HOME doesn't move either.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    old = _install_old("codex", None, scope=Scope.GLOBAL)
    assert old == home / ".codex/prompts/logging.md"

    result = _migrate("--agent", "codex", "--scope", "global")
    assert result.exit_code == 0, result.output
    assert not old.exists()
    assert (home / ".agents/skills/logging/SKILL.md").is_file()
    assert not (tmp_path / "codex-home").exists()


def test_migrate_global_kiro_follows_kiro_home(tmp_path, home, monkeypatch):
    kiro_home = tmp_path / "kiro-home"
    monkeypatch.setenv("KIRO_HOME", str(kiro_home))
    old = _install_old("kiro", None, scope=Scope.GLOBAL)
    assert old == kiro_home / "steering/logging.md"

    result = _migrate("--agent", "kiro", "--scope", "global")
    assert result.exit_code == 0, result.output
    assert not old.exists()
    assert (kiro_home / "skills/logging/SKILL.md").is_file()
    assert not home.exists()


def test_migrate_scope_without_an_old_format(project, home):
    # Copilot prompt files and Cursor rules were project-only
    result = _migrate("--agent", "copilot", "--agent", "cursor", "--scope", "global")
    assert result.exit_code == 0, result.output
    assert (
        result.output
        == "copilot:\n  nothing to migrate\n\ncursor:\n  nothing to migrate\n"
    )


def test_migrate_all_covers_every_agent_with_an_old_format(project):
    _install_old("kiro", project)
    result = _migrate("--agent", "all")
    assert result.exit_code == 0, result.output
    headers = [line for line in result.output.splitlines() if line.endswith(":")]
    assert headers == ["codex:", "copilot:", "cursor:", "kiro:"]
    assert "kiro:\n  migrated logging" in result.output


def test_migrate_rejects_an_agent_without_an_old_format():
    result = _migrate("--agent", "claude")
    assert result.exit_code == 2  # click usage error
    assert "'claude' is not one of" in result.output


def _hint_lines(output):
    return [line.strip() for line in output.splitlines() if "hint:" in line]


def test_status_hints_at_migrate(project):
    old = _install_old("codex", project)
    unstamped = project / ".codex/prompts/security-review.md"
    unstamped.write_text("from skilldeck 0.3.0\n")
    (project / ".codex/prompts/my-own-prompt.md").write_text("not a skill\n")

    result = CliRunner().invoke(cli, ["status", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    assert _hint_lines(result.output) == [
        f"hint: 2 codex skill(s) in an older format in {old.parent}; convert "
        "them with: skilldeck migrate --agent codex (1 unstamped or modified: "
        "add --force)"
    ]

    _migrate("--agent", "codex", "--force")
    result = CliRunner().invoke(cli, ["status", "--agent", "codex"])
    assert _hint_lines(result.output) == []


def test_status_hint_is_one_line_per_agent(project):
    for agent in ("copilot", "kiro"):
        _install_old(agent, project)
        _install_old(agent, project, "security-review")
    result = CliRunner().invoke(cli, ["status", "--agent", "all"])
    assert result.exit_code == 0, result.output
    hints = _hint_lines(result.output)
    assert len(hints) == 2
    assert hints[0].startswith("hint: 2 copilot skill(s)")
    assert hints[0].endswith("skilldeck migrate --agent copilot")
    assert hints[1].startswith("hint: 2 kiro skill(s)")
    assert "\n  hint: 2 kiro" in result.output  # under the kiro header


def test_status_hint_names_the_scope(home):
    _install_old("kiro", None, scope=Scope.GLOBAL)
    result = CliRunner().invoke(cli, ["status", "--agent", "kiro", "--scope", "global"])
    assert result.exit_code == 0, result.output
    (hint,) = _hint_lines(result.output)
    assert hint.endswith("skilldeck migrate --agent kiro --scope global")


def test_no_hint_without_old_installs(project):
    # a directory or a symlink at an old path isn't an old install
    (project / ".cursor/rules/logging.mdc").mkdir(parents=True)
    (project / ".cursor/rules/security-review.mdc").symlink_to(project / "gone")
    result = CliRunner().invoke(cli, ["status", "--agent", "all"])
    assert result.exit_code == 0, result.output
    assert _hint_lines(result.output) == []


def test_update_hints_at_migrate(project):
    _install_old("cursor", project)
    result = CliRunner().invoke(cli, ["update", "--agent", "cursor"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("nothing to update\nhint: 1 cursor skill(s)")
