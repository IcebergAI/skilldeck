import dataclasses
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

from skilldeck.adapters import (
    ADAPTERS,
    ALL_ADAPTERS,
    LEGACY_ADAPTERS,
    MIGRATIONS,
    InstallState,
    base,
)
from skilldeck.registry import Skill, SkillError, load_skill
from skilldeck.stamp import parse as parse_stamp
from skilldeck.targets import Scope


@pytest.fixture
def skill():
    return Skill(
        name="demo",
        description="a demo skill",
        category="testing",
        version="0.1.0",
        supported_agents=("claude", "codex", "copilot", "cursor"),
        body="DEMO BODY",
        path=Path("/nowhere"),
    )


def test_claude_renders_frontmatter(skill):
    out = ADAPTERS["claude"].render(skill)
    assert out.startswith("---\n")
    assert "name: demo" in out
    assert out.rstrip().endswith("DEMO BODY")


def _frontmatter(text):
    return yaml.safe_load(text.split("---\n")[1])


@pytest.mark.parametrize("agent", sorted(ADAPTERS))
def test_native_adapters_render_the_same_skill_md(agent, skill):
    # Every agent reads Agent Skills now; only the directories differ. The
    # Claude rendering is the reference: the plugin tree and the content
    # manifest hash it, so its bytes must not change.
    out = ADAPTERS[agent].render(skill)
    assert out == "---\nname: demo\ndescription: a demo skill\n---\n\nDEMO BODY"
    assert ADAPTERS[agent].creates_skill_dir


def test_skill_md_folds_a_long_description_as_yaml(skill):
    long = dataclasses.replace(skill, description="word " * 30 + "end.")
    out = ADAPTERS["codex"].render(long)
    assert _frontmatter(out)["description"] == long.description
    # folded onto a continuation line, as it always was: the bytes the plugin
    # tree hashes must not change
    assert "\n  word" in out.split("---\n")[1]


def test_cursor_rule_renders_agent_requested_rule(skill):
    out = LEGACY_ADAPTERS["cursor-rule"].render(skill)
    assert _frontmatter(out) == {"description": "a demo skill", "alwaysApply": False}
    assert out.endswith("\n\nDEMO BODY")


def _mdc_line_fields(text):
    """Cursor's .mdc reader: one ``key: value`` per line, not YAML. A value is
    trimmed and loses one pair of matching outer quotes; nothing inside them
    is unescaped."""
    fields = {}
    for line in text.split("---\n")[1].splitlines():
        if line.startswith((" ", "\t")) or ":" not in line:
            continue  # continuation lines are dropped
        key, value = line.split(":", 1)
        value = value.strip()
        if value[:1] in ("'", '"') and value[:1] == value[-1:]:
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def test_cursor_rule_keeps_a_long_description_on_one_line(skill):
    # Cursor reads .mdc frontmatter a line at a time, so a folded description
    # would reach it cut off at the first line break.
    long = dataclasses.replace(skill, description="word " * 30 + "end.")
    out = LEGACY_ADAPTERS["cursor-rule"].render(long)
    assert _mdc_line_fields(out)["description"] == long.description
    assert _frontmatter(out)["description"] == long.description


@pytest.mark.parametrize(
    "description",
    [
        "Don't miss: the reviewer's checklist",  # YAML would double the '
        "'quoted' at both ends",
        "It's plain",
        'a "quoted" word: kept',
        "a demo skill",
    ],
)
def test_cursor_rule_description_reads_back_verbatim_in_cursor(skill, description):
    # Cursor strips a value's quotes but doesn't unescape it, so a quoting
    # that doubles an apostrophe would reach it with the apostrophe doubled.
    quoted = dataclasses.replace(skill, description=description)
    out = LEGACY_ADAPTERS["cursor-rule"].render(quoted)
    assert _mdc_line_fields(out)["description"] == description
    assert _frontmatter(out) == {"description": description, "alwaysApply": False}


def test_cursor_rule_refuses_a_description_cursor_would_misread(skill):
    # no quoting reads back verbatim: single quotes double the apostrophe,
    # double quotes escape the double quote
    bad = dataclasses.replace(skill, description='Don\'t say "never": ok')
    with pytest.raises(SkillError, match="Cursor doesn't unescape"):
        LEGACY_ADAPTERS["cursor-rule"].render(bad)


def test_copilot_prompt_runs_in_agent_mode(skill):
    # Without ``agent: agent`` a prompt file runs in the chat's current mode,
    # which may be Ask, where the review can't run git or read files.
    out = LEGACY_ADAPTERS["copilot-prompt"].render(skill)
    assert _frontmatter(out) == {"description": "a demo skill", "agent": "agent"}
    assert out.endswith("\n\nDEMO BODY")


def test_kiro_steering_renders_manual_inclusion_frontmatter(skill):
    # Kiro steering defaults to always-on inclusion; on-demand review skills
    # must opt out via ``inclusion: manual`` or they steer every interaction.
    out = LEGACY_ADAPTERS["kiro-steering"].render(skill)
    assert _frontmatter(out) == {"inclusion": "manual"}
    assert out.endswith("\n\nDEMO BODY")


def test_codex_prompt_migration_source_renders_the_body(skill):
    # the old Codex custom-prompt format, kept only for ``migrate``
    (source,) = MIGRATIONS["codex"]
    assert source.render(skill) == "DEMO BODY"
    assert source.name not in ALL_ADAPTERS  # no longer an install target


@pytest.mark.parametrize("agent", ["cursor-rule", "copilot-prompt"])
def test_project_only_adapters_reject_global_scope(agent, skill, tmp_path):
    adapter = LEGACY_ADAPTERS[agent]
    with pytest.raises(SkillError, match="does not support --scope global"):
        adapter.install(skill, Scope.GLOBAL)
    # project scope works
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.is_file()


def test_claude_frontmatter_does_not_allow_injection():
    # A description with a newline + extra YAML key must NOT inject a frontmatter
    # field; it has to round-trip as a single quoted scalar.
    nasty = Skill(
        name="demo",
        description="harmless\nallowed-tools: ['*']",
        category="c",
        version="1",
        supported_agents=("claude",),
        body="BODY",
        path=Path("/nowhere"),
    )
    out = ADAPTERS["claude"].render(nasty)
    frontmatter = out.split("---\n")[1]
    parsed = yaml.safe_load(frontmatter)
    assert set(parsed) == {"name", "description"}  # no injected key
    assert parsed["description"] == "harmless\nallowed-tools: ['*']"
    assert out.endswith("\n\nBODY")


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


#: (adapter, project-scope path, global-scope path relative to $HOME)
LOCATIONS = [
    ("claude", ".claude/skills/demo/SKILL.md", ".claude/skills/demo/SKILL.md"),
    ("codex", ".agents/skills/demo/SKILL.md", ".agents/skills/demo/SKILL.md"),
    ("copilot", ".github/skills/demo/SKILL.md", ".copilot/skills/demo/SKILL.md"),
    ("cursor", ".cursor/skills/demo/SKILL.md", ".cursor/skills/demo/SKILL.md"),
    ("kiro", ".kiro/skills/demo/SKILL.md", ".kiro/skills/demo/SKILL.md"),
    ("copilot-prompt", ".github/prompts/demo.prompt.md", None),
    ("cursor-rule", ".cursor/rules/demo.mdc", None),
    ("kiro-steering", ".kiro/steering/demo.md", ".kiro/steering/demo.md"),
]


@pytest.mark.parametrize("agent,project,user", LOCATIONS)
def test_install_locations(agent, project, user, skill, tmp_path, home):
    adapter = ALL_ADAPTERS[agent]
    project_root = tmp_path / "repo"
    assert adapter.relative_path(skill) == Path(project)
    assert adapter.destination(skill, Scope.PROJECT, project_root) == (
        project_root / project
    )
    if user is None:
        assert adapter.scopes == (Scope.PROJECT,)
        with pytest.raises(SkillError, match="does not support --scope global"):
            adapter.destination(skill, Scope.GLOBAL)
    else:
        assert adapter.scopes == (Scope.PROJECT, Scope.GLOBAL)
        assert adapter.destination(skill, Scope.GLOBAL) == home / user


@pytest.mark.parametrize("agent,project,user", LOCATIONS)
def test_install_and_orphan_glob_in_every_scope(agent, project, user, tmp_path, home):
    adapter = ALL_ADAPTERS[agent]
    demo = _bare_skill("demo", "claude", "B")
    scopes = [Scope.PROJECT] + ([Scope.GLOBAL] if user else [])
    for scope in scopes:
        dest = adapter.install(demo, scope, project_root=tmp_path)
        assert dest == adapter.destination(demo, scope, project_root=tmp_path)
        assert adapter.installed_files(scope, project_root=tmp_path) == [dest]
        assert adapter.inspect(demo, scope, project_root=tmp_path)[0] is (
            InstallState.CURRENT
        )
        assert adapter.uninstall(demo, scope, project_root=tmp_path) == dest
        assert adapter.installed_files(scope, project_root=tmp_path) == []


def test_claude_config_dir_moves_global_skills(skill, tmp_path, home, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-work"))
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.GLOBAL)
    assert dest == tmp_path / "claude-work/skills/demo/SKILL.md"
    assert adapter.installed_files(Scope.GLOBAL) == [dest]
    assert not (home / ".claude").exists()
    # project scope is unaffected
    assert adapter.destination(skill, Scope.PROJECT, tmp_path) == (
        tmp_path / ".claude/skills/demo/SKILL.md"
    )


def test_empty_claude_config_dir_is_refused(skill, home, monkeypatch):
    # Claude Code does not fall back to ~/.claude for an empty value: it
    # resolves the config dir against its working directory. There is no
    # stable place to install to, so refuse rather than guess.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
    adapter = ADAPTERS["claude"]
    with pytest.raises(SkillError, match="CLAUDE_CONFIG_DIR is set but empty"):
        adapter.install(skill, Scope.GLOBAL)
    with pytest.raises(SkillError, match="CLAUDE_CONFIG_DIR is set but empty"):
        adapter.installed_files(Scope.GLOBAL)
    assert not home.exists()


@pytest.mark.parametrize("value", ["relative/dir", "~/.claude-work"])
def test_relative_config_dir_is_refused(skill, home, monkeypatch, value):
    # a relative path (or a "~" no shell expanded) depends on the agent's cwd
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", value)
    with pytest.raises(SkillError, match="not an absolute path"):
        ADAPTERS["claude"].destination(skill, Scope.GLOBAL)


@pytest.mark.parametrize(
    "agent,var,subpath",
    [
        ("copilot", "COPILOT_HOME", "skills/demo/SKILL.md"),
        ("kiro", "KIRO_HOME", "skills/demo/SKILL.md"),
        ("kiro-steering", "KIRO_HOME", "steering/demo.md"),
    ],
)
def test_config_home_env_vars(agent, var, subpath, skill, tmp_path, home, monkeypatch):
    adapter = ALL_ADAPTERS[agent]
    default = adapter.destination(skill, Scope.GLOBAL)
    monkeypatch.setenv(var, str(tmp_path / "moved"))
    assert adapter.destination(skill, Scope.GLOBAL) == tmp_path / "moved" / subpath
    # like the agents, an empty value means unset
    monkeypatch.setenv(var, "")
    assert adapter.destination(skill, Scope.GLOBAL) == default
    monkeypatch.setenv(var, "relative")
    with pytest.raises(SkillError, match=f"{var}='relative' is not an absolute"):
        adapter.destination(skill, Scope.GLOBAL)


def test_codex_home_does_not_move_codex_skills(skill, tmp_path, home, monkeypatch):
    # Codex reads ~/.agents/skills from the home directory whatever CODEX_HOME
    # says; skilldeck's old custom prompts were written under ~/.codex too.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    assert ADAPTERS["codex"].destination(skill, Scope.GLOBAL) == (
        home / ".agents/skills/demo/SKILL.md"
    )
    (source,) = MIGRATIONS["codex"]
    assert source.destination(skill, Scope.GLOBAL) == home / ".codex/prompts/demo.md"


def test_supports_respects_supported_agents(skill):
    assert ADAPTERS["claude"].supports(skill)
    assert not ADAPTERS["kiro"].supports(skill)


def test_legacy_adapters_follow_their_agent(skill):
    # legacy formats apply wherever their base agent does, so no meta.yaml
    # has to list them
    assert LEGACY_ADAPTERS["cursor-rule"].supports(skill)
    assert LEGACY_ADAPTERS["copilot-prompt"].supports(skill)
    assert not LEGACY_ADAPTERS["kiro-steering"].supports(skill)
    for source in (s for sources in MIGRATIONS.values() for s in sources):
        assert source.agent in ADAPTERS


def test_legacy_names_are_not_agents_a_skill_can_list(tmp_path):
    # ``supported-agents`` names agents, not formats: the registry still
    # rejects anything but the native adapters' names.
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "meta.yaml").write_text(
        "name: demo\ndescription: d\ncategory: c\nversion: 0.1.0\n"
        "supported-agents: [copilot-prompt]\n"
        "capabilities: {schema: 1, files: {read: repo, write: none}, commands: [],"
        " network: [], credentials: [], tools: [], artifacts: []}\n",
        encoding="utf-8",
    )
    (skill_dir / "skill.md").write_text("body\n", encoding="utf-8")
    with pytest.raises(SkillError, match="unknown agent.*copilot-prompt"):
        load_skill(skill_dir, known_agents=set(ADAPTERS))


def test_install_and_uninstall_roundtrip(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.is_file()
    assert dest == tmp_path / ".claude/skills/demo/SKILL.md"

    removed = adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert removed == dest
    assert not dest.exists()
    # the per-skill directory is cleaned up, not left empty
    assert not dest.parent.exists()
    # second uninstall is a no-op
    assert adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path) is None


def test_install_writes_a_valid_stamp(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    found = parse_stamp(dest.read_text(encoding="utf-8"))
    assert found is not None
    assert (found.name, found.version, found.modified) == ("demo", "0.1.0", False)
    assert adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.CURRENT
    )


def test_install_refuses_to_clobber_local_modifications(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    dest.write_text(
        dest.read_text(encoding="utf-8").replace("DEMO BODY", "my local tweak"),
        encoding="utf-8",
    )

    state, _ = adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)
    assert state is InstallState.MODIFIED
    with pytest.raises(SkillError, match="local modifications"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert "my local tweak" in dest.read_text(encoding="utf-8")  # not clobbered

    adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert "my local tweak" not in dest.read_text(encoding="utf-8")


def test_install_refuses_to_clobber_unmanaged_file(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_text("hand-written skill\n", encoding="utf-8")

    state, _ = adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)
    assert state is InstallState.UNMANAGED
    with pytest.raises(SkillError, match="no skilldeck stamp"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)

    adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert "DEMO BODY" in dest.read_text(encoding="utf-8")


def test_inspect_detects_stale_install(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    newer = Skill(
        name=skill.name,
        description=skill.description,
        category=skill.category,
        version="0.2.0",
        supported_agents=skill.supported_agents,
        body="NEW BODY",
        path=skill.path,
    )
    state, found = adapter.inspect(newer, Scope.PROJECT, project_root=tmp_path)
    assert state is InstallState.STALE
    assert found is not None and found.version == "0.1.0"
    # a stale (but unmodified) install may be overwritten without force
    adapter.install(newer, Scope.PROJECT, project_root=tmp_path)
    assert adapter.inspect(newer, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.CURRENT
    )


def test_installed_files_finds_installs(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert adapter.installed_files(Scope.PROJECT, project_root=tmp_path) == [dest]


def test_install_reports_unwritable_destination_cleanly(skill, tmp_path):
    # If a parent of the destination exists as a regular file, install must
    # raise SkillError (clean CLI message), not leak an OSError traceback.
    (tmp_path / ".claude").write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(SkillError, match="cannot install"):
        ADAPTERS["claude"].install(skill, Scope.PROJECT, project_root=tmp_path)


def test_install_refuses_to_write_through_symlink(skill, tmp_path, symlink):
    adapter = ADAPTERS["claude"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    target = tmp_path / "outside.txt"
    target.write_text("original", encoding="utf-8")
    symlink(dest, target)

    with pytest.raises(SkillError, match="symlink"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert target.read_text(encoding="utf-8") == "original"  # link target not clobbered


def _bare_skill(name, agent, body):
    return Skill(
        name=name,
        description="d",
        category="c",
        version="1",
        supported_agents=(agent,),
        body=body,
        path=Path("/nowhere"),
    )


@pytest.mark.parametrize("agent", sorted(LEGACY_ADAPTERS))
def test_uninstall_keeps_shared_directory(tmp_path, agent):
    # The legacy formats write into a directory shared by all skills
    # (.github/prompts, .cursor/rules, .kiro/steering). Cleanup must reclaim
    # only a per-skill <name>/ dir, never these shared dirs.
    adapter = LEGACY_ADAPTERS[agent]
    alpha = _bare_skill("alpha", adapter.agent, "A")
    beta = _bare_skill("beta", adapter.agent, "B")

    dest_alpha = adapter.install(alpha, Scope.PROJECT, project_root=tmp_path)
    dest_beta = adapter.install(beta, Scope.PROJECT, project_root=tmp_path)
    shared_dir = dest_alpha.parent
    assert shared_dir == dest_beta.parent

    # Removing one skill leaves the sibling and the shared dir intact.
    adapter.uninstall(alpha, Scope.PROJECT, project_root=tmp_path)
    assert not dest_alpha.exists()
    assert dest_beta.exists()
    assert shared_dir.is_dir()

    # Removing the LAST skill must still leave the shared dir — this is the case
    # a naive "rmdir when empty" cleanup would wrongly delete.
    adapter.uninstall(beta, Scope.PROJECT, project_root=tmp_path)
    assert not dest_beta.exists()
    assert shared_dir.is_dir()


@pytest.mark.parametrize(
    "agent,name",
    [
        ("copilot-prompt", "prompts"),
        ("cursor-rule", "rules"),
        ("kiro-steering", "steering"),
    ],
)
def test_uninstall_keeps_shared_dir_named_like_the_skill(tmp_path, agent, name):
    # A skill named after the shared directory itself (a skill "steering" in
    # .kiro/steering) must not trick cleanup into removing that dir.
    adapter = LEGACY_ADAPTERS[agent]
    skill = _bare_skill(name, adapter.agent, "B")
    adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    shared_dir = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path).parent
    assert shared_dir.is_dir()


def test_uninstall_keeps_the_shared_skills_root(tmp_path):
    # a SKILL.md adapter removes the skill's own directory, never the root
    adapter = ADAPTERS["codex"]
    skill = _bare_skill("skills", "codex", "B")
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert not dest.parent.exists()
    assert (tmp_path / ".agents/skills").is_dir()


def test_uninstall_refuses_unmanaged_file_unless_forced(skill, tmp_path):
    # #95: uninstall deletes, so it must honour the same stamp checks as install.
    adapter = LEGACY_ADAPTERS["cursor-rule"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_text("my own rule\n", encoding="utf-8")

    with pytest.raises(
        SkillError, match="no skilldeck stamp.*0.3.0 or earlier.*--force"
    ):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.read_text(encoding="utf-8") == "my own rule\n"

    removed = adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert removed == dest
    assert not dest.exists()


def test_uninstall_refuses_modified_install_unless_forced(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    dest.write_text(dest.read_text(encoding="utf-8") + "local edit\n", encoding="utf-8")

    with pytest.raises(SkillError, match="local modifications.*--force"):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert "local edit" in dest.read_text(encoding="utf-8")

    adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert not dest.exists()
    assert not dest.parent.exists()


def test_uninstall_removes_a_stale_install_without_force(skill, tmp_path):
    adapter = ADAPTERS["codex"]
    adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    newer = dataclasses.replace(skill, version="0.2.0", body="NEW BODY")
    assert adapter.inspect(newer, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.STALE
    )
    assert adapter.uninstall(newer, Scope.PROJECT, project_root=tmp_path) is not None


def test_symlink_to_a_stamped_file_is_not_treated_as_an_install(
    skill, tmp_path, symlink
):
    # skilldeck never creates symlinks, so inspect must not follow one to a
    # stamped file elsewhere and report it as a managed (deletable) install.
    adapter = ADAPTERS["codex"]
    elsewhere = tmp_path / "other-project"
    target = adapter.install(skill, Scope.PROJECT, project_root=elsewhere)
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    symlink(dest, target)

    assert adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path) == (
        InstallState.UNMANAGED,
        None,
    )
    with pytest.raises(SkillError, match="symlink"):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.is_symlink()

    adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert not dest.is_symlink()
    assert target.is_file()  # the link target is never deleted
    assert parse_stamp(target.read_text(encoding="utf-8")) is not None


def test_dangling_symlink_is_present_not_missing(skill, tmp_path, symlink):
    adapter = ADAPTERS["kiro"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    symlink(dest, tmp_path / "gone")
    state, _ = adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)
    assert state is InstallState.UNMANAGED
    adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert not dest.is_symlink()


def test_non_utf8_file_is_unmanaged_not_a_crash(skill, tmp_path):
    adapter = ADAPTERS["cursor"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"\xff\xfe binary rule")
    assert adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.UNMANAGED
    )
    with pytest.raises(SkillError, match="no skilldeck stamp"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    with pytest.raises(SkillError, match="no skilldeck stamp"):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.read_bytes() == b"\xff\xfe binary rule"


def test_directory_at_destination_is_never_removed(skill, tmp_path):
    adapter = ADAPTERS["codex"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.mkdir(parents=True)
    (dest / "keep.txt").write_text("keep", encoding="utf-8")
    assert adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.UNMANAGED
    )
    with pytest.raises(SkillError, match="is a directory, which skilldeck never del"):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    # nor replaced: a clean refusal, not an os.replace error naming a temp file
    with pytest.raises(SkillError, match="is a directory, which skilldeck never rep"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert _leftovers(dest.parent) == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX FIFOs")
def test_inspect_does_not_block_on_a_fifo(skill, tmp_path):
    adapter = ADAPTERS["codex"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    os.mkfifo(dest)
    assert adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.UNMANAGED
    )
    for action in (adapter.install, adapter.uninstall):
        with pytest.raises(SkillError, match="is a special file"):
            action(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert stat.S_ISFIFO(dest.lstat().st_mode)


def test_uninstall_force_removes_a_file_it_cannot_read(skill, tmp_path, monkeypatch):
    # Deleting needs only the directory entry, so --force must not be blocked
    # by a read failure -- install --force can already replace such a file.
    adapter = ADAPTERS["cursor"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    real_read_text = Path.read_text

    def unreadable(self, *args, **kwargs):
        if self == dest:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(SkillError, match="cannot read"):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.exists()
    assert adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert not dest.exists()


def _leftovers(directory):
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


def test_install_leaves_no_temp_files(skill, tmp_path):
    dest = ADAPTERS["codex"].install(skill, Scope.PROJECT, project_root=tmp_path)
    assert _leftovers(dest.parent) == []


def test_failed_install_keeps_the_old_file_and_cleans_up(skill, tmp_path, monkeypatch):
    # #98: installs write a sibling temp file and os.replace it into place, so a
    # failure part-way leaves the previous install intact and no debris behind.
    adapter = ADAPTERS["codex"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    before = dest.read_text(encoding="utf-8")
    newer = dataclasses.replace(skill, version="0.2.0", body="NEW BODY")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(base.os, "replace", boom)
    with pytest.raises(SkillError, match="cannot install demo.*disk full"):
        adapter.install(newer, Scope.PROJECT, project_root=tmp_path)
    assert dest.read_text(encoding="utf-8") == before
    assert _leftovers(dest.parent) == []


def test_interrupted_install_cleans_up_its_temp_file(skill, tmp_path, monkeypatch):
    adapter = ADAPTERS["codex"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)

    def interrupt(fd):
        raise KeyboardInterrupt

    monkeypatch.setattr(base.os, "fsync", interrupt)
    with pytest.raises(KeyboardInterrupt):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert not dest.exists()
    assert _leftovers(dest.parent) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_install_file_modes(skill, tmp_path):
    adapter = ADAPTERS["codex"]
    old_umask = os.umask(0o022)
    try:
        dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
        # a new file gets the umask-derived mode a plain write would give it
        assert stat.S_IMODE(dest.stat().st_mode) == 0o644
        # an overwrite keeps the mode the user chose
        dest.chmod(0o600)
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600
        # ... but never leaves a skill its owner (the agent) can't read
        dest.chmod(0o220)
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
        assert stat.S_IMODE(dest.stat().st_mode) == 0o620
        assert parse_stamp(dest.read_text(encoding="utf-8")) is not None
    finally:
        os.umask(old_umask)


def test_install_refuses_a_read_only_destination(skill, tmp_path, monkeypatch):
    # os.replace only needs the directory to be writable, so without this check
    # a file the user made read-only would be silently replaced. (Patched
    # rather than chmod'ed: root may write to any file.)
    adapter = ADAPTERS["codex"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    before = dest.read_text(encoding="utf-8")
    newer = dataclasses.replace(skill, version="0.2.0", body="NEW BODY")
    real_access = os.access
    monkeypatch.setattr(
        base.os,
        "access",
        lambda path, mode: False if Path(path) == dest else real_access(path, mode),
    )
    with pytest.raises(SkillError, match="is read-only"):
        adapter.install(newer, Scope.PROJECT, project_root=tmp_path, force=True)
    assert dest.read_text(encoding="utf-8") == before
    assert _leftovers(dest.parent) == []


def test_check_scope(skill):
    ADAPTERS["claude"].check_scope(Scope.GLOBAL)
    ADAPTERS["cursor"].check_scope(Scope.GLOBAL)
    with pytest.raises(SkillError, match="does not support --scope global"):
        LEGACY_ADAPTERS["cursor-rule"].check_scope(Scope.GLOBAL)


def _scope_error(adapter, scope, **kwargs):
    with pytest.raises(SkillError) as excinfo:
        adapter.check_scope(scope, **kwargs)
    return str(excinfo.value)


def test_scope_error_suggests_the_native_adapter_only_for_installs():
    # another adapter installs the skill elsewhere; for status, uninstall or
    # update it would act on different files from the ones asked about
    rule = LEGACY_ADAPTERS["cursor-rule"]
    assert _scope_error(rule, Scope.GLOBAL).endswith(
        "for that scope. Use --scope project"
    )
    assert _scope_error(rule, Scope.GLOBAL, installing=True).endswith(
        "Use --scope project, or --agent cursor (Agent Skills), which supports "
        "--scope global"
    )


def test_scope_error_without_an_alternative(monkeypatch):
    # a project-only adapter whose agent has no global location either can
    # only point at the scope it does have
    monkeypatch.setattr(ADAPTERS["cursor"], "global_dir", None)
    message = _scope_error(
        LEGACY_ADAPTERS["cursor-rule"], Scope.GLOBAL, installing=True
    )
    assert message.endswith("for that scope. Use --scope project")


def test_write_atomic_writes_lf_on_every_platform(tmp_path):
    # installs must be byte-identical across operating systems; text mode on
    # Windows would otherwise translate each "\n" to "\r\n"
    from skilldeck.adapters.base import write_atomic

    dest = tmp_path / "SKILL.md"
    write_atomic(dest, "line one\nline two\n")
    assert dest.read_bytes() == b"line one\nline two\n"
