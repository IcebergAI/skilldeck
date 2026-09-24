import dataclasses
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

from skilldeck.adapters import ADAPTERS, InstallState, base
from skilldeck.registry import Skill, SkillError
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


def test_codex_renders_body_as_is(skill):
    assert ADAPTERS["codex"].render(skill) == "DEMO BODY"


def test_cursor_renders_agent_requested_rule(skill):
    out = ADAPTERS["cursor"].render(skill)
    frontmatter = yaml.safe_load(out.split("---\n")[1])
    assert frontmatter == {"description": "a demo skill", "alwaysApply": False}
    assert out.endswith("\n\nDEMO BODY")


def test_copilot_renders_prompt_frontmatter(skill):
    out = ADAPTERS["copilot"].render(skill)
    frontmatter = yaml.safe_load(out.split("---\n")[1])
    assert frontmatter == {"description": "a demo skill"}
    assert out.endswith("\n\nDEMO BODY")


@pytest.mark.parametrize("agent", ["cursor", "copilot"])
def test_project_only_adapters_reject_global_scope(agent, skill, tmp_path):
    adapter = ADAPTERS[agent]
    with pytest.raises(SkillError, match="does not support --scope global"):
        adapter.install(skill, Scope.GLOBAL)
    # project scope works
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.is_file()


def test_kiro_renders_manual_inclusion_frontmatter(skill):
    # Kiro steering defaults to always-on inclusion; on-demand review skills
    # must opt out via ``inclusion: manual`` or they steer every interaction.
    out = ADAPTERS["kiro"].render(skill)
    frontmatter = yaml.safe_load(out.split("---\n")[1])
    assert frontmatter == {"inclusion": "manual"}
    assert out.endswith("\n\nDEMO BODY")


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


def test_global_scope_resolves_against_home(skill, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    dest = ADAPTERS["claude"].destination(skill, Scope.GLOBAL)
    assert dest == tmp_path / ".claude/skills/demo/SKILL.md"


def test_paths_are_agent_specific(skill):
    assert ADAPTERS["claude"].relative_path(skill) == Path(
        ".claude/skills/demo/SKILL.md"
    )
    assert ADAPTERS["codex"].relative_path(skill) == Path(".codex/prompts/demo.md")
    assert ADAPTERS["kiro"].relative_path(skill) == Path(".kiro/steering/demo.md")
    assert ADAPTERS["cursor"].relative_path(skill) == Path(".cursor/rules/demo.mdc")
    assert ADAPTERS["copilot"].relative_path(skill) == Path(
        ".github/prompts/demo.prompt.md"
    )


def test_supports_respects_supported_agents(skill):
    assert ADAPTERS["claude"].supports(skill)
    assert not ADAPTERS["kiro"].supports(skill)


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
    found = parse_stamp(dest.read_text())
    assert found is not None
    assert (found.name, found.version, found.modified) == ("demo", "0.1.0", False)
    assert adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.CURRENT
    )


def test_install_refuses_to_clobber_local_modifications(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    dest.write_text(dest.read_text().replace("DEMO BODY", "my local tweak"))

    state, _ = adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)
    assert state is InstallState.MODIFIED
    with pytest.raises(SkillError, match="local modifications"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert "my local tweak" in dest.read_text()  # not clobbered

    adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert "my local tweak" not in dest.read_text()


def test_install_refuses_to_clobber_unmanaged_file(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_text("hand-written skill\n")

    state, _ = adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)
    assert state is InstallState.UNMANAGED
    with pytest.raises(SkillError, match="no skilldeck stamp"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)

    adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert "DEMO BODY" in dest.read_text()


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
    (tmp_path / ".claude").write_text("a file, not a directory")
    with pytest.raises(SkillError, match="cannot install"):
        ADAPTERS["claude"].install(skill, Scope.PROJECT, project_root=tmp_path)


def test_install_refuses_to_write_through_symlink(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    target = tmp_path / "outside.txt"
    target.write_text("original")
    dest.symlink_to(target)

    with pytest.raises(SkillError, match="symlink"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert target.read_text() == "original"  # link target not clobbered


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


@pytest.mark.parametrize("agent", ["codex", "kiro"])
def test_uninstall_keeps_shared_directory(tmp_path, agent):
    # codex/kiro write into a directory shared by all skills (.codex/prompts,
    # .kiro/steering). Cleanup must reclaim only Claude's per-skill <name>/ dir,
    # never these shared dirs.
    adapter = ADAPTERS[agent]
    alpha = _bare_skill("alpha", agent, "A")
    beta = _bare_skill("beta", agent, "B")

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


@pytest.mark.parametrize("agent,name", [("codex", "prompts"), ("kiro", "steering")])
def test_uninstall_keeps_shared_dir_named_like_the_skill(tmp_path, agent, name):
    # A skill named after the shared directory itself (codex skill "prompts",
    # kiro skill "steering") must not trick cleanup into removing that dir.
    adapter = ADAPTERS[agent]
    skill = _bare_skill(name, agent, "B")
    adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    shared_dir = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path).parent
    assert shared_dir.is_dir()


def test_uninstall_refuses_unmanaged_file_unless_forced(skill, tmp_path):
    # #95: uninstall deletes, so it must honour the same stamp checks as install.
    adapter = ADAPTERS["cursor"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_text("my own rule\n")

    with pytest.raises(
        SkillError, match="no skilldeck stamp.*0.3.0 or earlier.*--force"
    ):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.read_text() == "my own rule\n"

    removed = adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert removed == dest
    assert not dest.exists()


def test_uninstall_refuses_modified_install_unless_forced(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    dest.write_text(dest.read_text() + "local edit\n")

    with pytest.raises(SkillError, match="local modifications.*--force"):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert "local edit" in dest.read_text()

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


def test_symlink_to_a_stamped_file_is_not_treated_as_an_install(skill, tmp_path):
    # skilldeck never creates symlinks, so inspect must not follow one to a
    # stamped file elsewhere and report it as a managed (deletable) install.
    adapter = ADAPTERS["codex"]
    elsewhere = tmp_path / "other-project"
    target = adapter.install(skill, Scope.PROJECT, project_root=elsewhere)
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.symlink_to(target)

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
    assert parse_stamp(target.read_text()) is not None


def test_dangling_symlink_is_present_not_missing(skill, tmp_path):
    adapter = ADAPTERS["kiro"]
    dest = adapter.destination(skill, Scope.PROJECT, project_root=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.symlink_to(tmp_path / "gone")
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
    (dest / "keep.txt").write_text("keep")
    assert adapter.inspect(skill, Scope.PROJECT, project_root=tmp_path)[0] is (
        InstallState.UNMANAGED
    )
    with pytest.raises(SkillError, match="is a directory, which skilldeck never del"):
        adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    # nor replaced: a clean refusal, not an os.replace error naming a temp file
    with pytest.raises(SkillError, match="is a directory, which skilldeck never rep"):
        adapter.install(skill, Scope.PROJECT, project_root=tmp_path, force=True)
    assert (dest / "keep.txt").read_text() == "keep"
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
    before = dest.read_text()
    newer = dataclasses.replace(skill, version="0.2.0", body="NEW BODY")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(base.os, "replace", boom)
    with pytest.raises(SkillError, match="cannot install demo.*disk full"):
        adapter.install(newer, Scope.PROJECT, project_root=tmp_path)
    assert dest.read_text() == before
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
        assert parse_stamp(dest.read_text()) is not None
    finally:
        os.umask(old_umask)


def test_install_refuses_a_read_only_destination(skill, tmp_path, monkeypatch):
    # os.replace only needs the directory to be writable, so without this check
    # a file the user made read-only would be silently replaced. (Patched
    # rather than chmod'ed: root may write to any file.)
    adapter = ADAPTERS["codex"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    before = dest.read_text()
    newer = dataclasses.replace(skill, version="0.2.0", body="NEW BODY")
    real_access = os.access
    monkeypatch.setattr(
        base.os,
        "access",
        lambda path, mode: False if Path(path) == dest else real_access(path, mode),
    )
    with pytest.raises(SkillError, match="is read-only"):
        adapter.install(newer, Scope.PROJECT, project_root=tmp_path, force=True)
    assert dest.read_text() == before
    assert _leftovers(dest.parent) == []


def test_check_scope(skill):
    ADAPTERS["claude"].check_scope(Scope.GLOBAL)
    with pytest.raises(SkillError, match="does not support --scope global"):
        ADAPTERS["cursor"].check_scope(Scope.GLOBAL)
