"""``skilldeck migrate`` and the ``status``/``update`` hints that point to it."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck.adapters import ADAPTERS, MIGRATIONS, InstallState
from skilldeck.adapters.base import yaml_frontmatter
from skilldeck.cli import cli
from skilldeck.registry import discover_skills
from skilldeck.stamp import parse, stamp
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
    return MIGRATIONS[agent][0].install(_skill(name), scope, project_root=root)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(path):
    return path.read_text(encoding="utf-8")


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
        for source in MIGRATIONS[agent]:
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
    assert ADAPTERS[agent].render(_skill("logging")) in _read(new)
    found = parse(_read(new))
    assert found is not None and not found.modified
    assert old.parent.is_dir()  # a shared directory, never removed

    status = CliRunner().invoke(cli, ["status", "--agent", agent])
    assert "up to date" in status.output.split("logging")[1].split("\n")[0]
    assert "hint" not in status.output


def _main_copilot_prompt(skill):
    # what the Copilot adapter wrote before this format became copilot-prompt:
    # no ``agent: agent``
    return yaml_frontmatter({"description": skill.description}) + "\n" + skill.body


def _main_cursor_rule(skill):
    # what the Cursor adapter wrote before this format became cursor-rule: a
    # long description folded onto a second line
    fields = {"description": skill.description, "alwaysApply": False}
    return yaml_frontmatter(fields) + "\n" + skill.body


@pytest.mark.parametrize(
    ("agent", "render", "version"),
    [
        ("copilot", _main_copilot_prompt, None),
        ("cursor", _main_cursor_rule, None),
        ("copilot", _main_copilot_prompt, "0.0.1"),
        ("kiro", lambda skill: MIGRATIONS["kiro"][0].render(skill), "0.0.1"),
    ],
)
def test_migrate_moves_a_stale_install_without_force(project, agent, render, version):
    # Real upgrades start from what an earlier skilldeck rendered, stamped:
    # stale for today's legacy adapters, but still unedited installs.
    old, new = (project / p for p in MOVES[agent])
    skill = _skill("security-review")
    old = old.with_name(old.name.replace("logging", skill.name))
    new = new.parent.with_name(skill.name) / new.name
    _write(old, stamp(render(skill), skill.name, version or skill.version))
    source = MIGRATIONS[agent][0]
    assert source.inspect(skill, Scope.PROJECT)[0] is InstallState.STALE

    status = CliRunner().invoke(cli, ["status", "--agent", agent])
    (hint,) = _hint_lines(status.output)
    assert hint.endswith(f"skilldeck migrate --agent {agent}")  # no --force

    result = _migrate("--agent", agent)
    assert result.exit_code == 0, result.output
    assert f"migrated {skill.name}: {old} -> {new}" in result.output
    assert not old.exists()
    assert parse(_read(new)) is not None


def test_migrate_is_idempotent(project):
    old, new = (project / p for p in MOVES["copilot"])
    _install_old("copilot", project)
    assert _migrate("--agent", "copilot").exit_code == 0
    migrated = _read(new)

    result = _migrate("--agent", "copilot")
    assert result.exit_code == 0, result.output
    assert result.output == "nothing to migrate\n"
    assert _read(new) == migrated and not old.exists()


def test_migrate_leaves_a_modified_install_unless_forced(project):
    old, new = (project / p for p in MOVES["cursor"])
    _install_old("cursor", project)
    _write(old, _read(old) + "my team's addition\n")

    result = _migrate("--agent", "cursor")
    assert result.exit_code == 0, result.output
    assert f"skip logging: {old} has local modifications; left in place" in (
        result.output
    )
    assert "my team's addition" in _read(old)
    assert not new.exists()

    result = _migrate("--agent", "cursor", "--force")
    assert result.exit_code == 0, result.output
    assert "migrated logging" in result.output
    assert not old.exists()
    assert "my team's addition" not in _read(new)


@pytest.mark.parametrize("agent", ["codex", "kiro"])
def test_migrate_leaves_an_unstamped_file_unless_forced(project, agent):
    # skilldeck 0.3.0 and earlier wrote Codex prompts and Kiro steering files
    # as the bare body, unstamped; but a file at the old path may just as
    # well be the user's own: #95 rules apply.
    old, new = (project / p for p in MOVES[agent])
    body = _skill("logging").body
    _write(old, body)

    result = _migrate("--agent", agent)
    assert result.exit_code == 0, result.output
    assert f"skip logging: {old} has no skilldeck stamp" in result.output
    assert "skilldeck 0.3.0 or earlier" in result.output
    assert _read(old) == body
    assert not new.exists()

    result = _migrate("--agent", agent, "--force")
    assert result.exit_code == 0, result.output
    assert not old.exists()
    assert parse(_read(new)) is not None


@pytest.mark.parametrize("agent", ["copilot", "cursor"])
def test_migrate_never_touches_unstamped_files_where_skilldeck_always_stamped(
    project, agent, symlink
):
    # Every Copilot prompt file and Cursor rule skilldeck ever wrote was
    # stamped, so an unstamped one (or a symlink) at a skill's old path is the
    # user's own, e.g. a team's .github/prompts/security-review.prompt.md.
    old, new = (project / p for p in MOVES[agent])
    _write(old, "our team's own checklist\n")
    link = old.with_name(old.name.replace("logging", "security-review"))
    symlink(link, old)

    status = CliRunner().invoke(cli, ["status", "--agent", agent])
    assert _hint_lines(status.output) == []
    for flags in ([], ["--force"]):
        result = _migrate("--agent", agent, *flags)
        assert result.exit_code == 0, result.output
        assert result.output == "nothing to migrate\n"
    assert _read(old) == "our team's own checklist\n"
    assert link.is_symlink()
    assert not new.exists()


def test_migrate_force_removes_a_symlink_but_not_its_target(project, symlink):
    old, new = (project / p for p in MOVES["kiro"])
    target = project / "shared/logging.md"
    _write(target, "shared steering\n")
    old.parent.mkdir(parents=True)
    symlink(old, target)

    result = _migrate("--agent", "kiro")
    assert result.exit_code == 0, result.output
    assert "is a symlink skilldeck did not create; left in place" in result.output
    assert old.is_symlink() and not new.exists()

    result = _migrate("--agent", "kiro", "--force")
    assert result.exit_code == 0, result.output
    assert not old.is_symlink() and new.is_file()
    assert _read(target) == "shared steering\n"


def test_migrate_never_removes_a_directory(project):
    old, new = (project / p for p in MOVES["codex"])
    old.mkdir(parents=True)
    result = _migrate("--agent", "codex", "--force")
    assert result.exit_code == 0, result.output
    assert f"skip logging: {old} is a directory, which skilldeck never removes" in (
        result.output
    )
    assert old.is_dir() and not new.exists()


@pytest.mark.parametrize("flags", [[], ["--force"]])
def test_migrate_keeps_a_modified_native_install(project, flags):
    # A locally edited SKILL.md is already the migrated skill: migrate removes
    # the old file and leaves the edits alone, --force or not.
    old, new = (project / p for p in MOVES["copilot"])
    CliRunner().invoke(cli, ["install", "logging", "--agent", "copilot"])
    _write(new, _read(new) + "edited\n")
    _install_old("copilot", project)

    result = _migrate("--agent", "copilot", *flags)
    assert result.exit_code == 0, result.output
    assert (
        f"migrated logging: removed {old}; kept the locally modified {new}"
        in result.output
    )
    assert not old.exists()
    assert "edited" in _read(new)


def test_migrate_force_is_about_the_old_file_only(project):
    # The upgrade case: an unstamped 0.3.0 prompt needs --force, which must
    # not also overwrite a customised SKILL.md already at the new location.
    old, new = (project / p for p in MOVES["codex"])
    CliRunner().invoke(cli, ["install", "logging", "--agent", "codex"])
    _write(new, _read(new) + "my customization\n")
    _write(old, _skill("logging").body)

    result = _migrate("--agent", "codex", "--force")
    assert result.exit_code == 0, result.output
    assert "kept the locally modified" in result.output
    assert not old.exists()
    assert "my customization" in _read(new)


@pytest.mark.parametrize("flags", [[], ["--force"]])
def test_migrate_never_overwrites_a_file_it_did_not_write(project, flags):
    # e.g. a skill of the same name from another tool in the shared
    # .agents/skills folder
    old, new = (project / p for p in MOVES["codex"])
    _write(new, "someone else's skill\n")
    _install_old("codex", project)

    result = _migrate("--agent", "codex", *flags)
    assert result.exit_code == 1
    assert (
        f"error: cannot migrate logging: {new} has no skilldeck stamp, and "
        "migrate never replaces what skilldeck didn't write" in result.output
    )
    assert "(the old file is kept)" in result.output
    assert _read(new) == "someone else's skill\n"
    assert old.is_file()

    # adopting it first lets the migration finish
    install = CliRunner().invoke(
        cli, ["install", "logging", "--agent", "codex", "--force"]
    )
    assert install.exit_code == 0, install.output
    result = _migrate("--agent", "codex")
    assert result.exit_code == 0, result.output
    assert not old.exists()


def test_migrate_never_replaces_a_symlink_at_the_new_location(project, symlink):
    old, new = (project / p for p in MOVES["kiro"])
    target = project / "shared/SKILL.md"
    _write(target, "shared skill\n")
    new.parent.mkdir(parents=True)
    symlink(new, target)
    _install_old("kiro", project)

    result = _migrate("--agent", "kiro", "--force")
    assert result.exit_code == 1
    assert f"cannot migrate logging: {new} is a symlink" in result.output
    assert "install --force" not in result.output  # install never replaces one
    assert new.is_symlink() and old.is_file()
    assert _read(target) == "shared skill\n"


def test_migrate_refreshes_a_stale_native_install(project):
    old, new = (project / p for p in MOVES["cursor"])
    _write(new, stamp("old body\n", "logging", "0.0.1"))
    _install_old("cursor", project)

    result = _migrate("--agent", "cursor")
    assert result.exit_code == 0, result.output
    assert f"migrated logging: {old} -> {new}" in result.output
    assert "old body" not in _read(new)
    state, _ = ADAPTERS["cursor"].inspect(_skill("logging"), Scope.PROJECT)
    assert state is InstallState.CURRENT


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


def test_migrate_global_kiro_checks_home_and_kiro_home(tmp_path, home, monkeypatch):
    # skilldeck used to write global steering files under ~/.kiro whatever
    # KIRO_HOME said; kiro-steering now follows KIRO_HOME. migrate finds both
    # and installs into $KIRO_HOME/skills, where Kiro reads skills.
    kiro_home = tmp_path / "kiro-home"
    monkeypatch.setenv("KIRO_HOME", str(kiro_home))
    at_home = _install_old("kiro", None, scope=Scope.GLOBAL)
    assert at_home == home / ".kiro/steering/logging.md"
    at_kiro_home = MIGRATIONS["kiro"][1].install(
        _skill("security-review"), Scope.GLOBAL
    )
    assert at_kiro_home == kiro_home / "steering/security-review.md"
    # an unstamped file is a possible 0.3.0 install only where 0.3.0 wrote
    _write(home / ".kiro/steering/test-review.md", _skill("test-review").body)
    _write(kiro_home / "steering/code-smells.md", "my own steering\n")

    status = CliRunner().invoke(cli, ["status", "--agent", "kiro", "--scope", "global"])
    (hint,) = _hint_lines(status.output)
    assert hint.startswith(
        "hint: 2 kiro skill(s) in an older format and 1 file(s) named like a "
        f"bundled skill without a skilldeck stamp in {at_home.parent}, "
        f"{at_kiro_home.parent}; convert them with: "
        "skilldeck migrate --agent kiro --scope global ("
    )

    result = _migrate("--agent", "kiro", "--scope", "global")
    assert result.exit_code == 0, result.output
    assert not at_home.exists() and not at_kiro_home.exists()
    for name in ("logging", "security-review"):
        assert (kiro_home / f"skills/{name}/SKILL.md").is_file()
    assert "skip test-review" in result.output
    assert "code-smells" not in result.output
    assert _read(kiro_home / "steering/code-smells.md") == "my own steering\n"
    assert not (home / ".kiro/skills").exists()


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
    _install_old("codex", project, "test-review")
    edited = project / ".codex/prompts/test-review.md"
    _write(edited, _read(edited) + "mine\n")
    _write(project / ".codex/prompts/security-review.md", "from skilldeck 0.3.0\n")
    _write(project / ".codex/prompts/my-own-prompt.md", "not a skill\n")

    result = CliRunner().invoke(cli, ["status", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    assert _hint_lines(result.output) == [
        "hint: 2 codex skill(s) in an older format and 1 file(s) named like a "
        f"bundled skill without a skilldeck stamp in {old.parent}; convert them "
        "with: skilldeck migrate --agent codex (1 locally modified: add --force; "
        "skilldeck 0.3.0 and earlier didn't stamp installs, so check the "
        "unstamped file(s) are old installs before adding --force)"
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
    # one source per directory: the two Kiro sources share .kiro/steering
    assert hints[1] == (
        f"hint: 2 kiro skill(s) in an older format in {project / '.kiro/steering'}; "
        "convert them with: skilldeck migrate --agent kiro"
    )
    assert "\n  hint: 2 kiro" in result.output  # under the kiro header


def test_status_hint_names_the_scope(home):
    _install_old("kiro", None, scope=Scope.GLOBAL)
    result = CliRunner().invoke(cli, ["status", "--agent", "kiro", "--scope", "global"])
    assert result.exit_code == 0, result.output
    (hint,) = _hint_lines(result.output)
    assert hint.endswith("skilldeck migrate --agent kiro --scope global")


def test_no_hint_without_old_installs(project, symlink):
    # a directory or a symlink at an old path isn't an old install
    (project / ".codex/prompts/logging.md").mkdir(parents=True)
    (project / ".kiro/steering").mkdir(parents=True)
    symlink(project / ".kiro/steering/security-review.md", project / "gone")
    result = CliRunner().invoke(cli, ["status", "--agent", "all"])
    assert result.exit_code == 0, result.output
    assert _hint_lines(result.output) == []


def test_update_hints_at_migrate(project):
    _install_old("cursor", project)
    result = CliRunner().invoke(cli, ["update", "--agent", "cursor"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("nothing to update\nhint: 1 cursor skill(s)")
