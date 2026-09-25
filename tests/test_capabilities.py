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
    GIT_BASELINE,
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


BASELINE_REVIEW = Capabilities(
    read="repo",
    commands=tuple(sorted(GIT_BASELINE)),
    network=("the git remote, via git fetch",),
)


def test_a_read_only_review_stays_within_the_baseline():
    caps = parse_capabilities(_raw())
    assert caps == Capabilities(read="repo")
    assert not caps.beyond_review_baseline
    assert not Capabilities().beyond_review_baseline
    # read-only git commands and the git remote they reach are the baseline
    assert not BASELINE_REVIEW.beyond_review_baseline
    assert not Capabilities(network=("the git remote",)).beyond_review_baseline
    for field, value in (
        ("write", "repo"),
        ("commands", ("git diff", "git push")),
        ("commands", ("git worktree add",)),
        ("commands", ("<the project's test command>",)),
        ("commands", ("npm audit",)),
        ("credentials", ("x",)),
        ("tools", ("x",)),
        ("artifacts", ("x.md",)),
    ):
        caps = Capabilities(read="repo", **{field: value})
        assert caps.beyond_review_baseline, (field, value)


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
        (_raw(commands=["sh ./check.sh"]), "run a script or inline code"),
        (_raw(commands=["sh check.sh"]), "run a script or inline code"),
        (_raw(commands=["python ../x.py"]), "run a script or inline code"),
        (_raw(commands=["python manage.py test"]), "run a script or inline code"),
        (_raw(commands=["python3 -c pass"]), "run a script or inline code"),
        (_raw(commands=["bash -c make"]), "run a script or inline code"),
        (_raw(commands=["bash -lc make"]), "run a script or inline code"),
        (_raw(commands=["node -e x"]), "run a script or inline code"),
        (_raw(commands=["node --eval x"]), "run a script or inline code"),
        (_raw(commands=["ruby app.rb"]), "run a script or inline code"),
        (_raw(commands=["perl -E say"]), "run a script or inline code"),
        (_raw(commands=["pwsh -Command Get-Item"]), "run a script or inline code"),
        (_raw(commands=["pwsh -File x"]), "run a script or inline code"),
        (_raw(commands=["zsh scripts\\x"]), "run a script or inline code"),
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


@pytest.mark.parametrize(
    "command",
    ["python -m pytest", "python3 -m pip_audit", "node --version", "git diff ./src"],
)
def test_interpreters_may_run_modules_and_other_programs_take_paths(command):
    assert parse_capabilities(_raw(commands=[command])).commands == (command,)


@pytest.mark.parametrize("path", ["review.md", "reports/review.md", ".skilldeck/r.md"])
def test_relative_artifact_paths_are_accepted(path):
    assert parse_capabilities(_raw(artifacts=[path])).artifacts == (path,)


# --- the notice adapters render -------------------------------------------------


def test_a_read_only_review_gets_no_notice():
    for caps in (Capabilities(read="repo"), BASELINE_REVIEW):
        assert notice(caps) == ""
        assert with_notice("body", caps) == "body"


def test_notice_tells_the_agent_everything_the_skill_asks_for():
    assert with_notice("# Demo\n", FULL) == (
        "# Demo\n"
        "\n"
        "## Declared capabilities\n"
        "\n"
        "Beyond reading the changed files, this skill asks you to:\n"
        "\n"
        "- run `git diff`, `<the project's test command>`\n"
        "- edit files in the repository\n"
        "- create `reports/review.md`\n"
        "- contact:\n"
        "  - the git remote, to fetch\n"
        "  - an advisory database\n"
        "- use these credentials: a registry token from NPM_TOKEN\n"
        "- use these agent tools: web fetch\n"
        "\n"
        "It asks for nothing else.\n"
    )
    # a body without a final newline still gets a blank line before the notice
    assert with_notice("# Demo", FULL).startswith("# Demo\n\n## Declared")


def test_notice_lists_baseline_commands_and_network_once_it_renders():
    caps = Capabilities(
        read="repo",
        write="repo",
        commands=("git fetch", "git diff"),
        network=("the git remote, via git fetch",),
    )
    assert notice(caps) == (
        "## Declared capabilities\n"
        "\n"
        "Beyond reading the repository, this skill asks you to:\n"
        "\n"
        "- run `git fetch`, `git diff`\n"
        "- edit files in the repository\n"
        "- contact the git remote, via git fetch\n"
        "\n"
        "It asks for nothing else.\n"
    )
    assert notice(Capabilities(tools=("web fetch", "web search"))) == (
        "## Declared capabilities\n"
        "\n"
        "This skill reads none of your files. It asks you to:\n"
        "\n"
        "- use these agent tools:\n"
        "  - web fetch\n"
        "  - web search\n"
        "\n"
        "It asks for nothing else.\n"
    )


def test_notice_speaks_to_the_agent_not_about_skilldeck():
    text = notice(FULL)
    for phrase in ("skilldeck", "schema", "enforce", "refuse"):
        assert phrase not in text.lower(), phrase


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
        Capabilities(read="repo", commands=("git diff", "npm audit")),
        Capabilities(read="repo", write="repo"),
        Capabilities(read="repo", credentials=("a token from GH_TOKEN",)),
        Capabilities(read="repo", tools=("web fetch",)),
        Capabilities(read="repo", artifacts=("review.md",)),
        FULL,
    ):
        rendered = adapter.render(_skill(caps))
        assert rendered.endswith(with_notice("# Demo\n\nDo the review.\n", caps))
        assert "\n## Declared capabilities\n" in rendered
    # a read-only review renders its body unchanged
    for caps in (Capabilities(read="repo"), BASELINE_REVIEW):
        plain = adapter.render(_skill(caps))
        assert plain.endswith("# Demo\n\nDo the review.\n")
        assert "Declared capabilities" not in plain


def test_installed_file_keeps_the_notice_above_the_stamp(tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(_skill(FULL), Scope.PROJECT, project_root=tmp_path)
    text = dest.read_text(encoding="utf-8")
    assert text == stamp(adapter.render(_skill(FULL)), "demo", "0.1.0")
    assert "It asks for nothing else.\n<!-- skilldeck " in text


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
        (".env", b"TOKEN=x\n", ".env is not meta.yaml or skill.md"),
        ("run.sh.bak", b"echo\n", "run.sh.bak is not meta.yaml or skill.md"),
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


JUNK = [
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "._skill.md",
    "skill.md~",
    "#skill.md#",
    ".skill.md.swp",
    ".meta.yaml.swo",
]


@pytest.mark.parametrize("name", JUNK)
def test_os_and_editor_leftovers_are_ignored_when_loading(tmp_path, name):
    skill_dir = _bundle(tmp_path)
    (skill_dir / name).write_bytes(b"\x00junk")
    assert registry.bundle_problems(skill_dir) == []
    assert load_skill(skill_dir).name == "demo"


def test_a_pycache_directory_is_ignored_when_loading(tmp_path):
    skill_dir = _bundle(tmp_path / "skills")
    (skill_dir / "__pycache__").mkdir()
    (skill_dir / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\x00")
    (tmp_path / "skills" / "__pycache__").mkdir()
    (tmp_path / "skills" / "Thumbs.db").write_bytes(b"\x00")
    assert [skill.name for skill in discover_skills(tmp_path / "skills")] == ["demo"]


def test_an_emacs_lock_symlink_is_ignored_but_other_junk_links_are_not(
    tmp_path, symlink
):
    skill_dir = _bundle(tmp_path)
    # Emacs writes its lock as a dangling symlink named .#<file>
    symlink(skill_dir / ".#skill.md", Path("user@host.1234"))
    assert load_skill(skill_dir).name == "demo"
    secret = tmp_path / "secret.txt"
    secret.write_text("token\n", encoding="utf-8")
    symlink(skill_dir / ".DS_Store", secret)
    with pytest.raises(SkillError, match=r"\.DS_Store is a symlink"):
        load_skill(skill_dir)


def test_leftovers_still_fail_provenance_verify(bundled_copy):
    for name in (".DS_Store", "skill.md~", ".skill.md.swp"):
        (bundled_copy / "logging" / name).write_bytes(b"\x00")
    # every command that loads the skills keeps working...
    assert discover_skills(bundled_copy)
    assert CliRunner().invoke(cli, ["list"]).exit_code == 0
    # ...but the release-integrity check reports them, as it always did
    assert verify_bundled_skills() == [
        "logging: unexpected file(s): .DS_Store, .skill.md.swp, skill.md~"
    ]
    assert CliRunner().invoke(cli, ["provenance", "--verify"]).exit_code == 1
    assert CliRunner().invoke(cli, ["catalog", "--json"]).exit_code == 1


def test_a_junction_counts_as_a_link(tmp_path, monkeypatch):
    # os.path.isjunction exists from Python 3.12 and is only ever true on
    # Windows; stand one in for the skill directory and one of its files
    skill_dir = _bundle(tmp_path / "skills")
    junctions = {skill_dir / "skill.md"}
    monkeypatch.setattr(
        os.path, "isjunction", lambda path: Path(path) in junctions, raising=False
    )
    with pytest.raises(SkillError, match="skill.md is a junction"):
        load_skill(skill_dir)
    junctions = {skill_dir}
    with pytest.raises(SkillError, match="the skill directory is a junction"):
        discover_skills(tmp_path / "skills")
    with pytest.raises(SkillError, match="the skill directory is a junction"):
        load_skill(skill_dir)


def test_a_junction_fails_provenance_verify(bundled_copy, monkeypatch):
    target = bundled_copy / "logging" / "meta.yaml"
    monkeypatch.setattr(
        os.path, "isjunction", lambda path: Path(path) == target, raising=False
    )
    assert verify_bundled_skills() == ["logging: meta.yaml is a junction"]


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


@pytest.mark.parametrize(
    "prose",
    [
        "Never set location.href = userInput from the query string.",
        "Check where src= comes from before trusting it.",
        "A <b>bold</b> claim, and a <placeholder> for a command.",
        'Para.\n\n    [indented](code.md)\n    <img src="code.png">\n\nText.',
        "Para.\n\n\t[tab-indented](code.md)\n",
    ],
)
def test_prose_and_indented_code_are_not_file_references(prose):
    assert local_links(prose) == []


@pytest.mark.parametrize(
    ("body", "found"),
    [
        ("An autolink: <file:///etc/passwd>.", ["file:///etc/passwd"]),
        ("<https://owasp.org/> and <mailto:a@example.com>", []),
        ('<a title="x"\n href="scripts/run.sh">run</a>', ["scripts/run.sh"]),
        (
            "- item\n\n    continued, with [a link](inside-list.md)\n",
            ["inside-list.md"],
        ),
        ("1. step\n    [lazy](cont.md)\n", ["cont.md"]),
        ("- item\n\nNot in the list.\n\n    [code](x.md)\n", []),
    ],
)
def test_link_check_edge_cases(body, found):
    assert local_links(body) == found


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


def test_provenance_verify_reports_symlinks_and_extra_files(bundled_copy, symlink):
    assert verify_bundled_skills() == []
    body = bundled_copy / "logging" / "skill.md"
    target = bundled_copy.parent / "logging-skill.md"
    body.rename(target)
    symlink(body, target)  # same bytes, so the digest still matches
    (bundled_copy / "code-smells" / "fix.py").write_text("x\n", encoding="utf-8")
    assert verify_bundled_skills() == [
        "code-smells: unexpected file(s): fix.py",
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
        and line.endswith("(matches the content manifest shipped in this package)")
        for line in lines
    )
    assert any(
        line.startswith("  verify:      ") and "skilldeck provenance --verify" in line
        for line in lines
    )
    assert "  deprecated:  no" in lines
    assert "    files:       reads the repository; edits no files" in lines
    assert any(
        line.startswith("    commands:    git fetch, git diff, git ls-files, npm audit")
        for line in lines
    )
    assert "    credentials: none" in lines
    assert (
        "    tools:       web fetch, to read advisory and package registry pages"
    ) in lines
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
    skills = {s.name: s for s in discover_skills()}
    result = CliRunner().invoke(cli, ["show", "logging", "--agent", "codex"])
    assert result.exit_code == 0, result.output
    assert result.output.endswith(rendered_body(skills["logging"]))
    assert "\n- edit files in the repository\n" in result.output
    # a read-only review is shown, and installed, exactly as its body
    plain = CliRunner().invoke(cli, ["show", "security-review", "--agent", "codex"])
    assert plain.output.endswith("\n\n" + skills["security-review"].body)
    assert "Declared capabilities" not in plain.output


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
    assert "(NOT in the content manifest shipped in this package)" in result.output
    assert "    commands:    git diff\n" in result.output
    assert not (tmp_path / ".claude").exists()


def test_install_dry_run_reports_a_path_that_cannot_hold_the_skill(
    tmp_path, monkeypatch
):
    # .claude/skills is a regular file, so creating the skill's folder fails
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "skills").write_text("not a folder\n", encoding="utf-8")
    args = ["install", "security-review", "--agent", "claude"]
    preview = CliRunner().invoke(cli, [*args, "--dry-run"])
    assert preview.exit_code == 1
    assert "would install" not in preview.output
    blocked = tmp_path.resolve() / ".claude" / "skills"
    assert f"cannot install security-review to {blocked}" in preview.output
    assert f"{blocked} is not a directory" in preview.output
    # the real install fails the same way
    real = CliRunner().invoke(cli, args)
    assert real.exit_code == 1
    assert f"error: cannot install security-review to {blocked}" in real.output


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
