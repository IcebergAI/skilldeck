"""Skill capability declarations and bundle validation (#73).

Covers the ``capabilities`` schema, the notice adapters render from it, the
bundle rules the registry enforces (built as adversarial skill directories in
``tmp_path``, never committed), and the install preview.
"""

import os
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from skilldeck import provenance, registry
from skilldeck.adapters import ADAPTERS, ALL_ADAPTERS
from skilldeck.adapters.base import rendered_body
from skilldeck.capabilities import (
    Capabilities,
    CapabilityError,
    notice,
    parse_capabilities,
    summary,
    with_notice,
)
from skilldeck.cli import cli
from skilldeck.provenance import verify_bundled_skills
from skilldeck.registry import (
    DEFAULT_SKILLS_DIR,
    Skill,
    SkillError,
    discover_skills,
    load_skill,
    local_links,
)
from skilldeck.stamp import stamp
from skilldeck.targets import Scope


def _raw(**overrides):
    """A decoded capability block that requests only reading the repository."""
    raw = {
        "schema": 1,
        "files": {"read": "repo", "write": "none"},
        "commands": [],
        "network": [],
        "credentials": [],
        "tools": [],
        "artifacts": [],
    }
    raw.update(overrides)
    return raw


FULL = Capabilities(
    read="diff",
    write="repo",
    commands=("git diff", "<the project's test command>"),
    network=("the git remote, to fetch", "an advisory database"),
    credentials=("a registry token from NPM_TOKEN",),
    tools=("web fetch",),
    artifacts=("reports/review.md",),
)


# --- the schema ---------------------------------------------------------------


def test_parse_reads_every_field():
    raw = _raw(
        files={"read": "diff", "write": "repo"},
        commands=["git diff", "<the project's test command>"],
        network=["the git remote, to fetch", "an advisory database"],
        credentials=["a registry token from NPM_TOKEN"],
        tools=["web fetch"],
        artifacts=["reports/review.md"],
    )
    assert parse_capabilities(raw) == FULL
    assert FULL.record() == {**raw, "schema": 1}


def test_read_only_declaration_requests_nothing_beyond_reading():
    caps = parse_capabilities(_raw())
    assert caps == Capabilities(read="repo")
    assert not caps.beyond_reading
    assert not Capabilities().beyond_reading
    for field, value in (
        ("write", "repo"),
        ("commands", ("git diff",)),
        ("network", ("x",)),
        ("credentials", ("x",)),
        ("tools", ("x",)),
        ("artifacts", ("x.md",)),
    ):
        assert Capabilities(**{field: value}).beyond_reading, field


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (None, "must be a mapping"),
        (["git diff"], "must be a mapping"),
        (_raw(network_access=True), "unknown field\\(s\\): network_access"),
        ({k: v for k, v in _raw().items() if k != "tools"}, "missing field.*tools"),
        ({k: v for k, v in _raw().items() if k != "schema"}, "missing.*schema"),
        (_raw(schema=2), "schema must be 1"),
        (_raw(schema="1"), "schema must be 1"),
        (_raw(schema=True), "schema must be 1"),
        (_raw(files="repo"), "files must be a mapping"),
        (_raw(files={"read": "repo"}), "files missing field.*write"),
        (_raw(files={"read": "repo", "write": "none", "x": 1}), "unknown field"),
        (_raw(files={"read": "all", "write": "none"}), "read must be one of"),
        (_raw(files={"read": "repo", "write": "diff"}), "write must be one of"),
        (_raw(files={"read": True, "write": "none"}), "read must be one of"),
        (_raw(commands="git diff"), "commands must be a list"),
        (_raw(commands=None), "commands must be a list"),
        (_raw(network=[1]), "entries must be strings"),
        (_raw(network=[""]), "must not be empty"),
        (_raw(network=["a\nb"]), "one line"),
        (_raw(network=["a\u2028b"]), "one line"),
        (_raw(network=[" padded"]), "leading or trailing"),
        (_raw(network=["x" * 201]), "limit is 200"),
        (_raw(tools=["web", "web"]), "more than once: web"),
        (_raw(commands=["`git diff`"]), "without shell operators"),
        (_raw(commands=["git  diff"]), "single-spaced"),
        (_raw(commands=["git diff | sh"]), "without shell operators"),
        (_raw(commands=["git diff; rm -rf ~"]), "without shell operators"),
        (_raw(commands=["git diff > out.txt"]), "without shell operators"),
        (_raw(commands=["git diff $(id)"]), "without shell operators"),
        (_raw(commands=["npm audit && npm ci"]), "without shell operators"),
        (_raw(commands=["<a> <b>"]), "without shell operators"),
        (_raw(commands=["./run.sh"]), "by its path"),
        (_raw(commands=["scripts/check.sh --all"]), "by its path"),
        (_raw(commands=["C:\\tools\\x.exe"]), "by its path"),
        (_raw(commands=["-rf"]), "must start with a program name"),
        (_raw(commands=["+x"]), "must start with a program name"),
    ],
)
def test_malformed_capabilities_are_rejected(raw, message):
    with pytest.raises(CapabilityError, match=message):
        parse_capabilities(raw)


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("../outside.md", "'..'"),
        ("reports/../../outside.md", "'..'"),
        ("./report.md", "'.'"),
        ("reports//review.md", "empty"),
        ("reports/", "empty"),
        ("/etc/passwd", "absolute"),
        ("C:/Windows/x.md", "drive"),
        ("c:x.md", "drive"),
        ("reports\\review.md", "separator"),
        ("..\\outside.md", "separator"),
        ("~/.ssh/config", "home"),
        ("my report.md", "only letters"),
    ],
)
def test_artifact_paths_must_stay_inside_the_project(path, reason):
    with pytest.raises(CapabilityError, match=f"inside the project: .*{reason}"):
        parse_capabilities(_raw(artifacts=[path]))


@pytest.mark.parametrize("path", ["review.md", "reports/review.md", ".skilldeck/r.md"])
def test_relative_artifact_paths_are_accepted(path):
    assert parse_capabilities(_raw(artifacts=[path])).artifacts == (path,)


# --- the notice adapters render -------------------------------------------------


def test_read_only_skills_get_no_notice():
    assert notice(Capabilities(read="repo")) == ""
    assert with_notice("body", Capabilities(read="repo")) == "body"


def test_notice_lists_what_the_skill_declares():
    assert with_notice("# Demo\n", FULL) == (
        "# Demo\n"
        "\n"
        "## Declared capabilities\n"
        "\n"
        "What this skill may ask for, as declared in its skilldeck metadata\n"
        "(capability schema 1). The declaration is for review: nothing enforces it.\n"
        "Anything not listed here is not requested by this skill.\n"
        "\n"
        "- Files: reads the changed files; may edit files in the repository\n"
        "- Commands: `git diff`, `<the project's test command>`\n"
        "- Network:\n"
        "  - the git remote, to fetch\n"
        "  - an advisory database\n"
        "- Credentials: a registry token from NPM_TOKEN\n"
        "- Agent tools: web fetch\n"
        "- Creates: `reports/review.md`\n"
    )
    # a body without a final newline still gets a blank line before the notice
    assert with_notice("# Demo", FULL).startswith("# Demo\n\n## Declared")


def _skill(capabilities, body="# Demo\n\nDo the review.\n"):
    return Skill(
        name="demo",
        description="A demo skill.",
        category="testing",
        version="0.1.0",
        supported_agents=tuple(ADAPTERS),
        body=body,
        path=Path("/nowhere"),
        capabilities=capabilities,
    )


@pytest.mark.parametrize("name", sorted(ALL_ADAPTERS))
def test_every_adapter_carries_the_notice(name):
    adapter = ALL_ADAPTERS[name]
    for caps in (
        Capabilities(read="repo", commands=("git diff",)),
        Capabilities(read="repo", network=("an advisory database",)),
        Capabilities(read="repo", credentials=("a token from GH_TOKEN",)),
        FULL,
    ):
        rendered = adapter.render(_skill(caps))
        assert rendered.endswith(with_notice("# Demo\n\nDo the review.\n", caps))
        assert "\n## Declared capabilities\n" in rendered
    # a skill that only reads renders its body unchanged
    plain = adapter.render(_skill(Capabilities(read="repo")))
    assert plain.endswith("# Demo\n\nDo the review.\n")
    assert "Declared capabilities" not in plain


def test_installed_file_keeps_the_notice_above_the_stamp(tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(_skill(FULL), Scope.PROJECT, project_root=tmp_path)
    text = dest.read_text(encoding="utf-8")
    assert text == stamp(adapter.render(_skill(FULL)), "demo", "0.1.0")
    assert "- Creates: `reports/review.md`\n<!-- skilldeck " in text


def test_summary_marks_what_is_not_requested():
    assert summary(Capabilities(read="repo", commands=("git fetch", "git diff"))) == [
        ("files", ("reads the repository; edits no files",)),
        ("commands", ("git fetch, git diff",)),
        ("network", ("none",)),
        ("credentials", ("none",)),
        ("tools", ("none",)),
        ("artifacts", ("none",)),
    ]
    assert dict(summary(FULL))["network"] == (
        "the git remote, to fetch",
        "an advisory database",
    )


# --- the bundle rules, on adversarial skill directories ------------------------

CAPABILITIES_YAML = """\
capabilities:
  schema: 1
  files: {read: repo, write: none}
  commands: [git diff]
  network: []
  credentials: []
  tools: []
  artifacts: []
"""


def _bundle(root: Path, name: str = "demo", body: str = "# Demo\n") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "meta.yaml").write_text(
        f"name: {name}\ndescription: A demo skill.\ncategory: testing\n"
        f"version: 0.1.0\nsupported-agents: [claude]\n{CAPABILITIES_YAML}",
        encoding="utf-8",
    )
    (skill_dir / "skill.md").write_text(body, encoding="utf-8")
    return skill_dir


def test_benign_bundle_loads_with_its_capabilities(tmp_path):
    skill = load_skill(_bundle(tmp_path))
    assert skill.capabilities == Capabilities(read="repo", commands=("git diff",))
    assert registry.bundle_problems(tmp_path / "demo") == []


def test_capabilities_are_required(tmp_path):
    skill_dir = _bundle(tmp_path)
    meta = skill_dir / "meta.yaml"
    text = meta.read_text(encoding="utf-8")
    meta.write_text(text[: text.index("capabilities:")], encoding="utf-8")
    with pytest.raises(SkillError, match="missing fields: capabilities"):
        load_skill(skill_dir)


def test_malformed_capabilities_name_the_skill(tmp_path):
    skill_dir = _bundle(tmp_path)
    meta = skill_dir / "meta.yaml"
    meta.write_text(
        meta.read_text(encoding="utf-8").replace("[git diff]", "[../x.sh]"),
        encoding="utf-8",
    )
    with pytest.raises(SkillError, match=r"demo: meta.yaml capabilities.commands"):
        load_skill(skill_dir)


@pytest.mark.parametrize(
    ("name", "content", "problem"),
    [
        ("run.sh", b"echo hi\n", "run.sh is an undeclared executable (a .sh file)"),
        (
            "check.PY",
            b"print(1)\n",
            "check.PY is an undeclared executable (a .py file)",
        ),
        ("tool.exe", b"MZ\x90\x00", "tool.exe is an undeclared executable (a .exe"),
        (
            "hook",
            b"#!/bin/sh\necho hi\n",
            "hook is an undeclared executable (it starts",
        ),
        ("helper", b"\x7fELF\x02\x01", "helper is an undeclared executable (a native"),
        ("notes.txt", b"just notes\n", "notes.txt is not meta.yaml or skill.md"),
        (".DS_Store", b"\x00\x00", ".DS_Store is not meta.yaml or skill.md"),
    ],
)
def test_extra_files_are_rejected(tmp_path, name, content, problem):
    skill_dir = _bundle(tmp_path)
    (skill_dir / name).write_bytes(content)
    with pytest.raises(SkillError) as caught:
        load_skill(skill_dir)
    assert problem in str(caught.value)
    assert "holds only meta.yaml and skill.md" in str(caught.value)


@pytest.mark.skipif(os.name == "nt", reason="Windows files have no execute bit")
def test_a_file_with_the_execute_bit_is_an_undeclared_executable(tmp_path):
    skill_dir = _bundle(tmp_path)
    script = skill_dir / "payload"
    script.write_text("rm -rf ~\n", encoding="utf-8")
    script.chmod(0o755)
    with pytest.raises(SkillError, match="payload is an undeclared executable "):
        load_skill(skill_dir)
    assert registry.bundle_problems(skill_dir) == [
        "payload is an undeclared executable (its execute bit is set)"
    ]


@pytest.mark.skipif(os.name == "nt", reason="Windows files have no execute bit")
def test_an_execute_bit_on_the_bundle_files_themselves_is_tolerated(tmp_path):
    # skilldeck reads them as text and never copies their mode, and some
    # filesystems (a Windows drive under WSL) mark every file executable
    skill_dir = _bundle(tmp_path)
    for name in ("meta.yaml", "skill.md"):
        (skill_dir / name).chmod(0o755)
    assert load_skill(skill_dir).name == "demo"


def test_a_directory_in_a_bundle_is_rejected(tmp_path):
    skill_dir = _bundle(tmp_path)
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "check.sh").write_text("echo\n", encoding="utf-8")
    with pytest.raises(SkillError, match="scripts is a directory"):
        load_skill(skill_dir)


@pytest.mark.parametrize("name", ["meta.yaml", "skill.md"])
def test_a_symlinked_bundle_file_is_rejected(tmp_path, symlink, name):
    skill_dir = _bundle(tmp_path)
    elsewhere = tmp_path / f"elsewhere-{name}"
    (skill_dir / name).rename(elsewhere)
    symlink(skill_dir / name, elsewhere)
    with pytest.raises(SkillError, match=f"{name} is a symlink"):
        load_skill(skill_dir)


def test_a_symlink_to_an_outside_file_is_rejected(tmp_path, symlink):
    skill_dir = _bundle(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("token\n", encoding="utf-8")
    symlink(skill_dir / "reference.md", secret)
    with pytest.raises(SkillError, match="reference.md is a symlink"):
        load_skill(skill_dir)


def test_a_symlinked_skill_directory_is_rejected(tmp_path, symlink):
    real = _bundle(tmp_path / "real")
    skills = tmp_path / "skills"
    skills.mkdir()
    symlink(skills / "demo", real)
    with pytest.raises(SkillError, match="the skill directory is a symlink"):
        discover_skills(skills)


@pytest.mark.parametrize(
    "link",
    [
        "[the guide](references/guide.md)",
        "![diagram](diagram.png)",
        "[up](../other-skill/skill.md)",
        "[abs](/etc/passwd)",
        "[file](file:///etc/passwd)",
        "[ref]\n\n[ref]: ./checklist.md",
        '<img src="logo.png" alt="logo">',
        "<a href='scripts/run.sh'>run</a>",
    ],
)
def test_links_to_files_the_skill_cannot_ship_are_rejected(tmp_path, link):
    skill_dir = _bundle(tmp_path, body=f"# Demo\n\nSee {link}.\n")
    with pytest.raises(SkillError, match="skill.md links to .*cannot ship"):
        load_skill(skill_dir)


def test_web_links_anchors_and_code_are_not_file_references():
    body = (
        "# Demo\n\n"
        "[OWASP](https://owasp.org/) and [plain](http://example.com), "
        "[mail](mailto:security@example.com), [below](#output), "
        "[proto](//example.com/x).\n\n"
        "A code span is not a link: `[x](relative.md)` or ``<img src=a.png>``.\n\n"
        "```markdown\n[fenced](relative.md)\n```\n\n"
        '~~~~\n<img src="inside.png">\n```\nstill fenced](x.md)\n~~~~\n'
    )
    assert local_links(body) == []
    assert local_links(body + "\n[after](after.md)\n") == ["after.md"]


def test_bundled_skills_link_only_to_the_web():
    for skill in discover_skills(known_agents=set(ADAPTERS)):
        assert local_links(skill.body) == [], skill.name


# --- provenance --verify applies the same rules --------------------------------


@pytest.fixture
def bundled_copy(tmp_path, monkeypatch):
    copy = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILLS_DIR, copy)
    monkeypatch.setattr(provenance, "DEFAULT_SKILLS_DIR", copy)
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", copy)
    return copy


def test_provenance_verify_reports_symlinks_and_executables(bundled_copy, symlink):
    assert verify_bundled_skills() == []
    body = bundled_copy / "logging" / "skill.md"
    target = bundled_copy.parent / "logging-skill.md"
    body.rename(target)
    symlink(body, target)  # same bytes, so the digest still matches
    (bundled_copy / "code-smells" / "fix.py").write_text("x\n", encoding="utf-8")
    assert verify_bundled_skills() == [
        "code-smells: fix.py is an undeclared executable (a .py file)",
        "logging: skill.md is a symlink",
    ]
    result = CliRunner().invoke(cli, ["provenance", "--verify"])
    assert result.exit_code == 1


# --- the preview: show --summary and install --dry-run -------------------------


def test_show_summary_prints_trust_and_capabilities():
    result = CliRunner().invoke(cli, ["show", "dependency-review", "--summary"])
    assert result.exit_code == 0, result.output
    skill = next(s for s in discover_skills() if s.name == "dependency-review")
    lines = result.output.splitlines()
    assert lines[0] == f"dependency-review {skill.version} (security)"
    assert (
        "  source:      https://github.com/IcebergAI/skilldeck, "
        "src/skilldeck/skills/dependency-review"
    ) in lines
    assert any(
        line.startswith("  digest:      sha256:")
        and line.endswith("(matches the content manifest)")
        for line in lines
    )
    assert "  deprecated:  no" in lines
    assert "    files:       reads the repository; edits no files" in lines
    assert any(
        line.startswith("    commands:    git fetch, git diff, git ls-files, npm audit")
        for line in lines
    )
    assert "    credentials: none" in lines
    assert "    tools:       web fetch, to read advisory pages" in lines
    # each network description on its own line
    network = lines.index(
        "    network:     the git remote, via git fetch, to bring the base branch "
        "up to date"
    )
    assert lines[network + 1].startswith(" " * 17 + "vulnerability databases")
    assert "# Dependency Review" not in result.output


def test_show_summary_and_agent_are_exclusive():
    result = CliRunner().invoke(
        cli, ["show", "security-review", "--summary", "--agent", "claude"]
    )
    assert result.exit_code == 2
    assert "--summary or --agent, not both" in result.output


def test_show_agent_prints_the_notice_that_is_installed():
    skill = next(s for s in discover_skills() if s.name == "security-review")
    result = CliRunner().invoke(cli, ["show", "security-review", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    assert result.output.endswith(rendered_body(skill))
    assert "- Commands: `git fetch`, `git diff`, `git ls-files`\n" in result.output


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_install_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = ["security-review", "--agent", "claude", "--agent", "kiro", "--dry-run"]
    result = CliRunner().invoke(cli, ["install", *args])
    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []
    out = result.output
    assert out.startswith("security-review ")
    assert "    commands:    git fetch, git diff, git ls-files\n" in out
    claude = tmp_path.resolve() / ".claude/skills/security-review/SKILL.md"
    kiro = tmp_path.resolve() / ".kiro/skills/security-review/SKILL.md"
    assert f"  claude: would install -> {claude}\n" in out
    assert f"  kiro: would install -> {kiro}\n" in out
    assert out.endswith("dry run: nothing was written\n")


def test_install_dry_run_reports_what_a_real_install_would_do(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    names = ["security-review", "logging", "code-smells"]
    assert runner.invoke(cli, ["install", *names, "--agent", "claude"]).exit_code == 0
    root = tmp_path / ".claude/skills"
    # logging: an older version; code-smells: edited by hand
    logging = root / "logging/SKILL.md"
    skill = next(s for s in discover_skills() if s.name == "logging")
    logging.write_text(
        stamp(ADAPTERS["claude"].render(skill), "logging", "0.0.1"), encoding="utf-8"
    )
    edited = root / "code-smells/SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "mine\n", "utf-8")
    before = _snapshot(tmp_path)

    result = runner.invoke(cli, ["install", *names, "--agent", "claude", "--dry-run"])
    assert result.exit_code == 1  # as the real install would, for code-smells
    assert _snapshot(tmp_path) == before
    assert "  claude: would rewrite (up to date) -> " in result.output
    assert f"  claude: would update (0.0.1 -> {skill.version}) -> " in result.output
    assert "has local modifications; re-run with --force" in result.output

    forced = runner.invoke(
        cli, ["install", *names, "--agent", "claude", "--dry-run", "--force"]
    )
    assert forced.exit_code == 0, forced.output
    assert "  claude: would overwrite local modifications -> " in forced.output
    assert _snapshot(tmp_path) == before


def test_install_dry_run_refuses_what_install_refuses(tmp_path, monkeypatch, symlink):
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / ".claude/skills/security-review/SKILL.md"
    dest.parent.mkdir(parents=True)
    target = tmp_path / "target.md"
    target.write_text("mine\n", encoding="utf-8")
    symlink(dest, target)
    result = CliRunner().invoke(
        cli, ["install", "security-review", "--agent", "claude", "--dry-run"]
    )
    assert result.exit_code == 1
    assert "refusing to install through symlink" in result.output
    assert target.read_text(encoding="utf-8") == "mine\n"


def test_install_dry_run_flags_a_skill_the_manifest_does_not_know(
    tmp_path, monkeypatch
):
    _bundle(tmp_path / "skills")
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", tmp_path / "skills")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli, ["install", "demo", "--agent", "claude", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "(NOT in the content manifest)" in result.output
    assert "    commands:    git diff\n" in result.output
    assert not (tmp_path / ".claude").exists()


def test_install_prints_nothing_new_without_dry_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli, ["install", "security-review", "--agent", "claude"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith("installed security-review -> ")
    assert "capabilities" not in result.output


# --- the bundled skills --------------------------------------------------------


def test_every_bundled_skill_declares_every_capability_explicitly():
    # load_skill requires every key; this pins that the files spell them out
    for skill_dir in sorted(DEFAULT_SKILLS_DIR.iterdir()):
        meta = yaml.safe_load((skill_dir / "meta.yaml").read_text(encoding="utf-8"))
        assert set(meta["capabilities"]) == {
            "schema",
            "files",
            "commands",
            "network",
            "credentials",
            "tools",
            "artifacts",
        }, skill_dir.name
