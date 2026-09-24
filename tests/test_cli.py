import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck.adapters import ADAPTERS, base
from skilldeck.cli import cli, main
from skilldeck.provenance import distribution_provenance
from skilldeck.registry import Skill, discover_skills
from skilldeck.stamp import stamp


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
    assert result.output.index("security:") < result.output.index(
        "\n  security-review "
    )


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


def test_uninstall_refuses_a_file_skilldeck_did_not_write(tmp_path, monkeypatch):
    # #95: a hand-written rule at the destination is not skilldeck's to delete.
    monkeypatch.chdir(tmp_path)
    own = tmp_path / ".cursor/rules/security-review.mdc"
    own.parent.mkdir(parents=True)
    own.write_text("my own hand-written rule\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["uninstall", "security-review", "--agent", "cursor-rule"]
    )
    assert result.exit_code == 1
    assert "has no skilldeck stamp" in result.output
    assert "--force" in result.output
    assert own.read_text(encoding="utf-8") == "my own hand-written rule\n"

    result = runner.invoke(
        cli, ["uninstall", "security-review", "--agent", "cursor-rule", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert not own.exists()


def test_uninstall_refuses_local_modifications(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "logging", "--agent", "cursor"])
    dest = tmp_path / ".cursor/skills/logging/SKILL.md"
    dest.write_text(dest.read_text(encoding="utf-8") + "local edit\n", encoding="utf-8")

    result = runner.invoke(cli, ["uninstall", "logging", "--agent", "cursor"])
    assert result.exit_code == 1
    assert "has local modifications" in result.output
    assert "local edit" in dest.read_text(encoding="utf-8")

    result = runner.invoke(
        cli, ["uninstall", "logging", "--agent", "cursor", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert not dest.exists()


def test_uninstall_reports_errors_and_keeps_going(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "--all", "--agent", "codex"])
    edited = tmp_path / ".agents/skills/logging/SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "mine\n", encoding="utf-8")

    result = runner.invoke(cli, ["uninstall", "--all", "--agent", "codex"])
    assert result.exit_code == 1
    assert "error:" in result.output and "SKILL.md has local modifications" in (
        result.output
    )
    remaining = sorted(p.name for p in (tmp_path / ".agents/skills").iterdir())
    assert remaining == ["logging"]  # every other skill was still removed


def test_uninstall_force_removes_a_symlink_but_not_its_target(
    tmp_path, monkeypatch, symlink
):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "team-rules/security-review.md"
    target.parent.mkdir()
    target.write_text("shared team prompt\n", encoding="utf-8")
    link = tmp_path / ".agents/skills/security-review/SKILL.md"
    link.parent.mkdir(parents=True)
    symlink(link, target)
    runner = CliRunner()

    result = runner.invoke(cli, ["uninstall", "security-review", "--agent", "codex"])
    assert result.exit_code == 1
    assert "is a symlink skilldeck did not create" in result.output
    assert link.is_symlink()

    result = runner.invoke(
        cli, ["uninstall", "security-review", "--agent", "codex", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert not link.is_symlink() and not link.exists()
    assert target.read_text(encoding="utf-8") == "shared team prompt\n"


@pytest.mark.parametrize("command", ["install", "uninstall"])
def test_names_and_all_are_mutually_exclusive(tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli, [command, "security-review", "--all", "--agent", "claude"]
    )
    assert result.exit_code == 2  # click usage error
    assert "not both" in result.output
    assert not (tmp_path / ".claude").exists()


def test_uninstall_reports_when_not_installed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli, ["uninstall", "security-review", "--agent", "claude"]
    )
    assert result.exit_code == 0
    assert "not installed for claude: security-review" in result.output


def test_install_to_multiple_agents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli,
        ["install", "security-review", "--agent", "claude", "--agent", "codex"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude/skills/security-review/SKILL.md").is_file()
    assert (tmp_path / ".agents/skills/security-review/SKILL.md").is_file()


NATIVE_DIRS = [
    ".claude/skills",
    ".agents/skills",
    ".github/skills",
    ".cursor/skills",
    ".kiro/skills",
]


def test_install_agent_all_targets_every_native_adapter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["install", "security-review", "--agent", "all"])
    assert result.exit_code == 0, result.output
    for root in NATIVE_DIRS:
        assert (tmp_path / root / "security-review/SKILL.md").is_file()
    # 'all' means the native skills folders, never the legacy formats
    for legacy in (".github/prompts", ".cursor/rules", ".kiro/steering"):
        assert not (tmp_path / legacy).exists()


def test_uninstall_from_multiple_agents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "security-review", "--agent", "all"])
    result = runner.invoke(
        cli, ["uninstall", "security-review", "--agent", "claude", "--agent", "kiro"]
    )
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".claude/skills/security-review/SKILL.md").exists()
    assert not (tmp_path / ".kiro/skills/security-review/SKILL.md").exists()
    assert (tmp_path / ".agents/skills/security-review/SKILL.md").is_file()


def test_show_prints_body():
    result = CliRunner().invoke(cli, ["show", "security-review"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("# Security Review")
    assert "---" not in result.output.split("\n", 1)[0]  # no frontmatter


def test_show_agent_renders_for_that_agent():
    result = CliRunner().invoke(cli, ["show", "security-review", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("---\n")  # claude frontmatter
    assert "name: security-review" in result.output


def test_show_renders_a_legacy_format():
    result = CliRunner().invoke(
        cli, ["show", "security-review", "--agent", "copilot-prompt"]
    )
    assert result.exit_code == 0, result.output
    assert "\nagent: agent\n" in result.output


def test_show_unknown_skill_fails():
    result = CliRunner().invoke(cli, ["show", "does-not-exist"])
    assert result.exit_code != 0
    assert isinstance(result.exception, Exception)


def test_provenance_reports_package_source_and_bundled_versions():
    result = CliRunner().invoke(cli, ["provenance", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema_version"] == 1
    assert data["distribution"]["name"] == "skilldeck"
    assert data["distribution"]["source_repository"] == (
        "https://github.com/IcebergAI/skilldeck"
    )
    assert data["distribution"]["source_ref"] is None
    assert data["distribution"]["source_commit"] is None
    expected = {skill.name: skill.version for skill in discover_skills()}
    actual = {skill["name"]: skill["version"] for skill in data["skills"]}
    assert actual == expected
    assert all(
        skill["canonical_sha256"].startswith("sha256:")
        and len(skill["canonical_sha256"]) == 71
        for skill in data["skills"]
    )


def test_provenance_human_output_is_readable():
    result = CliRunner().invoke(cli, ["provenance"])
    assert result.exit_code == 0, result.output
    assert "repository: https://github.com/IcebergAI/skilldeck" in result.output
    assert "source ref: unavailable" in result.output
    assert "security-review" in result.output
    assert "sha256:" in result.output


def test_install_over_modified_file_fails_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "security-review", "--agent", "claude"])
    dest = tmp_path / ".claude/skills/security-review/SKILL.md"
    dest.write_text(dest.read_text(encoding="utf-8") + "my tweak\n", encoding="utf-8")

    result = runner.invoke(cli, ["install", "security-review", "--agent", "claude"])
    assert result.exit_code == 1
    assert "local modifications" in result.output
    assert "my tweak" in dest.read_text(encoding="utf-8")

    result = runner.invoke(
        cli, ["install", "security-review", "--agent", "claude", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert "my tweak" not in dest.read_text(encoding="utf-8")


def test_status_reports_each_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        cli, ["install", "security-review", "test-review", "--agent", "claude"]
    )
    dest = tmp_path / ".claude/skills/test-review/SKILL.md"
    dest.write_text(dest.read_text(encoding="utf-8") + "my tweak\n", encoding="utf-8")

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
    orphan.write_text(
        stamp("left behind\n", "retired-skill", "0.1.0"), encoding="utf-8"
    )
    result = CliRunner().invoke(cli, ["status", "--agent", "claude"])
    assert result.exit_code == 0
    assert "orphan:" in result.output
    assert "retired-skill 0.1.0" in result.output


def test_status_orphans_flag_local_edits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orphan = tmp_path / ".agents/skills/retired/SKILL.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text(
        stamp("old\n", "retired", "0.1.0").replace("old", "mine"), encoding="utf-8"
    )
    result = CliRunner().invoke(cli, ["status", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    assert "(retired 0.1.0, modified locally)" in result.output


@pytest.mark.parametrize(
    "agent,relative",
    [
        ("copilot", ".github/skills/deploy/SKILL.md"),
        ("copilot-prompt", ".github/prompts/deploy.prompt.md"),
        ("cursor", ".cursor/skills/team-style/SKILL.md"),
        ("cursor-rule", ".cursor/rules/team-style.mdc"),
        ("codex", ".agents/skills/my-skill/SKILL.md"),
        ("kiro", ".kiro/skills/product/SKILL.md"),
        ("kiro-steering", ".kiro/steering/product.md"),
        ("claude", ".claude/skills/my-own-skill/SKILL.md"),
    ],
)
def test_status_ignores_users_own_files_in_shared_dirs(
    tmp_path, monkeypatch, agent, relative
):
    # The user's own prompts/rules live next to skilldeck's installs; only
    # files carrying a skilldeck stamp can be skilldeck orphans (#96).
    monkeypatch.chdir(tmp_path)
    own = tmp_path / relative
    own.parent.mkdir(parents=True)
    own.write_text("my prompt\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["status", "--agent", agent])
    assert result.exit_code == 0, result.output
    assert "orphan" not in result.output


def test_status_skips_unreadable_files_in_shared_dirs(tmp_path, monkeypatch, symlink):
    # Shared dirs can hold anything: binary files, directories, dangling links
    # whose names match the install glob. None of it may crash status (#96).
    monkeypatch.chdir(tmp_path)
    shared = tmp_path / ".cursor/rules"
    shared.mkdir(parents=True)
    (shared / "binary.mdc").write_bytes(b"\xff\xfe\x00 not utf-8")
    (shared / "a-directory.mdc").mkdir()
    symlink(shared / "dangling.mdc", tmp_path / "missing")
    stamped = tmp_path / "elsewhere.mdc"
    stamped.write_text(stamp("x\n", "linked", "1.0.0"), encoding="utf-8")
    symlink(shared / "linked.mdc", stamped)
    result = CliRunner().invoke(cli, ["status", "--agent", "cursor-rule"])
    assert result.exit_code == 0, result.output
    assert "orphan" not in result.output


def _status_line(output, skill):
    """The `skilldeck status` row for exactly ``skill``."""
    return next(line for line in output.splitlines() if line.split()[:1] == [skill])


def test_status_accepts_several_agents_with_headers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "security-review", "--agent", "codex"])
    result = runner.invoke(cli, ["status", "--agent", "claude", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    claude_part, codex_part = result.output.split("\ncodex:\n")
    assert claude_part.startswith("claude:\n")
    # match the whole skill name: frontend-security-review sorts before it
    assert "not installed" in _status_line(claude_part, "security-review")
    assert "up to date" in _status_line(codex_part, "security-review")


def test_status_agent_all_covers_every_adapter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["status", "--agent", "all"])
    assert result.exit_code == 0, result.output
    headers = [line for line in result.output.splitlines() if line.endswith(":")]
    assert headers == [f"{name}:" for name in sorted(ADAPTERS)]


def test_single_agent_status_has_no_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["status", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    assert "claude:" not in result.output


def test_agent_all_installs_every_native_adapter_globally(tmp_path, monkeypatch):
    # every agent now has a user-level skills folder, so 'all' covers them all
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    result = CliRunner().invoke(cli, ["status", "--agent", "all", "--scope", "global"])
    assert result.exit_code == 0, result.output
    assert "skip" not in result.output
    headers = [line for line in result.output.splitlines() if line.endswith(":")]
    assert headers == [f"{name}:" for name in sorted(ADAPTERS)]

    result = CliRunner().invoke(
        cli, ["install", "security-review", "--agent", "all", "--scope", "global"]
    )
    assert result.exit_code == 0, result.output
    for root in (
        ".claude/skills",
        ".agents/skills",
        ".copilot/skills",
        ".cursor/skills",
        ".kiro/skills",
    ):
        assert (tmp_path / root / "security-review/SKILL.md").is_file()


def test_agent_all_skips_agents_without_the_scope(tmp_path, monkeypatch):
    # 'all' means every agent that can install at the requested scope; one
    # without a location there is skipped with a note rather than failed.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(ADAPTERS["cursor"], "global_dir", None)
    result = CliRunner().invoke(cli, ["status", "--agent", "all", "--scope", "global"])
    assert result.exit_code == 0, result.output
    assert "skip cursor: no --scope global support" in result.output
    headers = [line for line in result.output.splitlines() if line.endswith(":")]
    assert headers == ["claude:", "codex:", "copilot:", "kiro:"]


def test_explicit_agent_without_the_scope_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    result = CliRunner().invoke(
        cli,
        ["status", "--agent", "cursor-rule", "--agent", "codex", "--scope", "global"],
    )
    assert result.exit_code == 1
    assert "error: cursor-rule does not support --scope global" in result.output
    # actionable: names the scope that works and the agent's native adapter
    assert "Use --scope project, or --agent cursor (Agent Skills)" in result.output
    assert "security-review" in result.output  # codex still reported


def test_explicit_agent_without_the_scope_is_an_error_even_with_all(
    tmp_path, monkeypatch
):
    # 'all' never includes the legacy formats; naming a project-only one with
    # --scope global is an error, and the rest still install.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    result = CliRunner().invoke(
        cli,
        ["install", "logging", "--agent", "all", "--agent", "copilot-prompt"]
        + ["--scope", "global"],
    )
    assert result.exit_code == 1
    assert "error: copilot-prompt does not support --scope global" in result.output
    assert "skip" not in result.output
    assert (tmp_path / ".agents/skills/logging/SKILL.md").is_file()
    assert not (tmp_path / ".github").exists()


def test_claude_config_dir_directs_global_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    config = tmp_path / "claude-work"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    runner = CliRunner()
    result = runner.invoke(
        cli, ["install", "logging", "--agent", "claude", "--scope", "global"]
    )
    assert result.exit_code == 0, result.output
    assert (config / "skills/logging/SKILL.md").is_file()
    assert not (tmp_path / "home").exists()
    orphan = config / "skills/retired/SKILL.md"
    orphan.parent.mkdir()
    orphan.write_text(stamp("old\n", "retired", "0.1.0"), encoding="utf-8")
    result = runner.invoke(cli, ["status", "--agent", "claude", "--scope", "global"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output.split("logging")[1].split("\n")[0]
    assert f"orphan: {orphan} (retired 0.1.0)" in result.output


def test_unusable_config_dir_is_an_error_for_that_agent_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
    result = CliRunner().invoke(
        cli, ["install", "logging", "--agent", "all", "--scope", "global"]
    )
    assert result.exit_code == 1
    assert "error: claude: CLAUDE_CONFIG_DIR is set but empty" in result.output
    assert not (tmp_path / ".claude").exists()
    assert (tmp_path / ".agents/skills/logging/SKILL.md").is_file()
    # project scope doesn't depend on it
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["install", "logging", "--agent", "claude"])
    assert result.exit_code == 0, result.output


def test_status_and_provenance_handle_an_empty_skill_list(monkeypatch):
    monkeypatch.setattr("skilldeck.cli.discover_skills", lambda **kw: [])
    result = CliRunner().invoke(cli, ["status", "--agent", "claude"])
    assert result.exit_code == 0, result.output

    real = distribution_provenance()
    monkeypatch.setattr(
        "skilldeck.cli.distribution_provenance", lambda: {**real, "skills": []}
    )
    result = CliRunner().invoke(cli, ["provenance"])
    assert result.exit_code == 0, result.output
    assert "bundled skills:\n  (none)" in result.output


def test_update_refreshes_stale_and_skips_modified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        cli, ["install", "security-review", "test-review", "--agent", "claude"]
    )
    stale = tmp_path / ".claude/skills/security-review/SKILL.md"
    # simulate an install from an older skilldeck: rewrite with an old stamp
    stale.write_text(stamp("old body\n", "security-review", "0.0.1"), encoding="utf-8")
    modified = tmp_path / ".claude/skills/test-review/SKILL.md"
    modified.write_text(
        modified.read_text(encoding="utf-8") + "my tweak\n", encoding="utf-8"
    )

    result = runner.invoke(cli, ["update", "--agent", "claude"])
    assert result.exit_code == 0, result.output
    assert "updated security-review (0.0.1 ->" in result.output
    assert "skip test-review: locally modified" in result.output
    assert "old body" not in stale.read_text(encoding="utf-8")
    assert "my tweak" in modified.read_text(encoding="utf-8")

    # --force also refreshes the modified install
    result = runner.invoke(cli, ["update", "--agent", "claude", "--force"])
    assert result.exit_code == 0, result.output
    assert "my tweak" not in modified.read_text(encoding="utf-8")


def test_update_with_nothing_installed_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["update", "--agent", "claude"])
    assert result.exit_code == 0
    assert "nothing to update" in result.output


def _make_stale(path, name):
    path.write_text(stamp("old body\n", name, "0.0.1"), encoding="utf-8")


def test_update_reports_an_error_and_keeps_going(tmp_path, monkeypatch):
    # One failing destination must not abort the rest of the update (#98).
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        cli, ["install", "security-review", "test-review", "--agent", "claude"]
    )
    skills_dir = tmp_path / ".claude/skills"
    _make_stale(skills_dir / "security-review/SKILL.md", "security-review")
    _make_stale(skills_dir / "test-review/SKILL.md", "test-review")

    real_write = base.write_atomic

    def flaky_write(dest, text):
        if dest.parent.name == "security-review":
            raise OSError("disk full")
        real_write(dest, text)

    monkeypatch.setattr(base, "write_atomic", flaky_write)
    result = runner.invoke(cli, ["update", "--agent", "claude"])
    assert result.exit_code == 1
    assert "error: cannot install security-review" in result.output
    assert "disk full" in result.output
    assert "updated test-review (0.0.1 ->" in result.output
    assert "old body" in (skills_dir / "security-review/SKILL.md").read_text(
        encoding="utf-8"
    )

    # with the only candidate failing, it doesn't also claim nothing to update
    result = runner.invoke(cli, ["update", "--agent", "claude"])
    assert result.exit_code == 1
    assert "error: cannot install security-review" in result.output
    assert "nothing to update" not in result.output


def test_update_accepts_several_agents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["install", "logging", "--agent", "claude", "--agent", "kiro"])
    _make_stale(tmp_path / ".kiro/skills/logging/SKILL.md", "logging")
    result = runner.invoke(cli, ["update", "--agent", "all"])
    assert result.exit_code == 0, result.output
    assert "claude:\n  nothing to update" in result.output
    assert "kiro:\n  updated logging (0.0.1 ->" in result.output
    assert "old body" not in (tmp_path / ".kiro/skills/logging/SKILL.md").read_text(
        encoding="utf-8"
    )


def test_update_leaves_a_symlinked_destination_alone(tmp_path, monkeypatch, symlink):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "shared-copy.md"
    target.write_text(stamp("old body\n", "logging", "0.0.1"), encoding="utf-8")
    dest = tmp_path / ".agents/skills/logging/SKILL.md"
    dest.parent.mkdir(parents=True)
    symlink(dest, target)
    result = CliRunner().invoke(cli, ["update", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    assert "skip logging: symlink, not managed by skilldeck" in result.output
    assert dest.is_symlink() and "old body" in target.read_text(encoding="utf-8")


def test_directory_at_an_install_path_is_not_offered_install_force(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agents/skills/logging/SKILL.md").mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    assert "logging" in result.output
    assert "directory, not managed by skilldeck" in result.output
    assert "adopt with" not in result.output
    result = runner.invoke(cli, ["update", "--agent", "codex"])
    assert "skip logging: directory, not managed by skilldeck" in result.output
    result = runner.invoke(cli, ["install", "logging", "--agent", "codex", "--force"])
    assert result.exit_code == 1
    assert "is a directory, which skilldeck never replaces" in result.output
    assert ".tmp" not in result.output


def test_main_reports_skill_error_cleanly(monkeypatch):
    # main() wraps cli() and turns a SkillError into a clean message, not a
    # traceback. An unknown skill name raises SkillError out of the command.
    monkeypatch.setattr(
        sys, "argv", ["skilldeck", "install", "does-not-exist", "--agent", "claude"]
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert "error: unknown skill: does-not-exist" in str(excinfo.value)
