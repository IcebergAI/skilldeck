"""``skilldeck new`` and ``skilldeck validate`` (#72).

A skill is scaffolded into a temporary skills directory, completed, validated,
rendered, installed and removed through the CLI; each validation rule is then
broken on purpose. Checkout mode runs against a minimal skilldeck checkout
built in ``tmp_path`` from this repository's own scripts, so the eval fixture
and generated-output checks run for real. Nothing here touches the network.
"""

import importlib.util
import json
import re
import shutil
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck import authoring, lint, registry
from skilldeck.adapters import ADAPTERS, ALL_ADAPTERS
from skilldeck.cli import cli
from skilldeck.provenance import canonical_json
from skilldeck.targets import Scope

ROOT = Path(__file__).resolve().parent.parent
NAME = "widget-review"
DESCRIPTION = "Review pending changes for widget misuse."
SOURCE = "Grounded in the [Widget Guide](https://example.org/widget-guide)."


def _runner():
    # Click < 8.2 mixes stderr into stdout unless told not to; 8.2 dropped the
    # flag and always captures the streams separately
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _invoke(*args, code=0):
    result = _runner().invoke(cli, [str(arg) for arg in args])
    assert result.exit_code == code, (result.stdout, result.stderr)
    return result


def _report(*args, code=1):
    return json.loads(_invoke("validate", "--json", *args, code=code).stdout)


def _rules(report, level=None):
    return {
        p["rule"] for p in report["problems"] if level is None or p["level"] == level
    }


def _new(skills_dir, name=NAME, *args):
    return _invoke("new", name, "--category", "review", "--dir", skills_dir, *args)


def _complete(skill_dir):
    """Write the content an author would: every placeholder filled, a cited
    source, and a real description."""
    body = (skill_dir / "skill.md").read_text(encoding="utf-8")
    body = body.replace(f"{lint.PLACEHOLDER}: ", "")
    body = body.replace(
        "## What to look for\n\n", f"## What to look for\n\n{SOURCE}\n\n"
    )
    (skill_dir / "skill.md").write_text(body, encoding="utf-8", newline="\n")
    meta = (skill_dir / "meta.yaml").read_text(encoding="utf-8")
    meta = meta.replace(repr(authoring.PLACEHOLDER_DESCRIPTION), DESCRIPTION)
    (skill_dir / "meta.yaml").write_text(meta, encoding="utf-8", newline="\n")
    assert lint.PLACEHOLDER not in body + meta


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    """An organization's skills directory, outside any checkout."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "skills"
    root.mkdir()
    return root


@pytest.fixture
def completed(skills_dir):
    _new(skills_dir)
    _complete(skills_dir / NAME)
    return skills_dir / NAME


# --- scaffolding ---------------------------------------------------------------


def test_new_scaffolds_meta_and_skeleton(skills_dir):
    out = _new(skills_dir).stdout
    skill_dir = skills_dir / NAME
    assert sorted(p.name for p in skill_dir.iterdir()) == ["meta.yaml", "skill.md"]
    assert f"created skills/{NAME}/meta.yaml" in out
    assert f"skilldeck validate --skills-dir skills {NAME}" in out
    # outside a checkout there is nowhere to put an eval fixture
    assert not (skills_dir.parent / "evals").exists()
    skill = registry.load_skill(skill_dir, set(ADAPTERS))
    assert skill.version == "0.1.0"
    assert skill.category == "review"
    assert skill.supported_agents == tuple(sorted(ADAPTERS))
    assert skill.body.startswith("# Widget Review\n")
    for path in skill_dir.iterdir():
        assert b"\r" not in path.read_bytes()


def test_new_takes_description_and_agents(skills_dir):
    _new(
        skills_dir,
        NAME,
        "--description",
        DESCRIPTION,
        "--agent",
        "codex",
        "--agent",
        "claude",
        "--agent",
        "codex",
    )
    skill = registry.load_skill(skills_dir / NAME, set(ADAPTERS))
    assert skill.description == DESCRIPTION
    assert skill.supported_agents == ("codex", "claude")


def test_generated_skill_passes_every_structural_check(skills_dir):
    # Before any content is written, the only problems are the honest
    # "incomplete" ones: placeholders remain and no source is cited yet.
    _new(skills_dir)
    skill = registry.load_skill(skills_dir / NAME, set(ADAPTERS))
    assert lint.structure_problems(skill.name, skill.body) == []
    assert lint.description_problems(skill.name, skill.description) == []
    report = _report("--skills-dir", skills_dir)
    assert _rules(report) == {"content.placeholder", "references.cited-source"}
    assert _rules(report, "error") == set()
    assert report["skills"] == [
        {
            "name": NAME,
            "path": f"skills/{NAME}",
            "checkout": False,
            "status": "incomplete",
        }
    ]
    placeholders = {
        p["path"]: p for p in report["problems"] if p["rule"] == "content.placeholder"
    }
    assert set(placeholders) == {f"skills/{NAME}/meta.yaml", f"skills/{NAME}/skill.md"}


def test_skeleton_states_no_domain_guidance():
    # everything outside the shared template is a placeholder
    text = authoring.SKILL_TEMPLATE
    assert not lint.LINK_RE.search(text)
    look_for = lint.section(text, "What to look for").strip()
    assert look_for.startswith(lint.PLACEHOLDER)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["Bad_Name", "--category", "x"], "invalid skill name"),
        ([NAME, "--category", ""], "--category must be a single non-empty line"),
        ([NAME, "--category", "x", "--description", "No period"], "ending with a"),
        ([NAME, "--category", "x", "--agent", "vscode"], "Invalid value for '--agent'"),
    ],
)
def test_new_rejects_bad_arguments(skills_dir, args, message):
    result = _invoke("new", *args, "--dir", skills_dir, code=2)
    assert message in result.stderr
    assert not (skills_dir / NAME).exists()


def test_new_never_overwrites(completed):
    before = (completed / "skill.md").read_text(encoding="utf-8")
    result = _invoke("new", NAME, "--category", "x", "--dir", completed.parent, code=2)
    assert "already exists" in result.stderr
    assert (completed / "skill.md").read_text(encoding="utf-8") == before


def test_new_needs_a_directory_outside_a_checkout(skills_dir):
    result = _invoke("new", NAME, "--category", "x", code=2)
    assert "not inside a skilldeck checkout" in result.stderr
    assert "--dir" in result.stderr


def test_new_never_writes_into_the_installed_package(tmp_path, monkeypatch):
    package = tmp_path / "site-packages" / "skilldeck"
    (package / "skills").mkdir(parents=True)
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", package / "skills")
    result = _invoke(
        "new", NAME, "--category", "x", "--dir", package / "skills", code=2
    )
    assert "inside the installed skilldeck package" in result.stderr
    assert not (package / "skills" / NAME).exists()


# --- the full lifecycle -----------------------------------------------------------


def test_generate_complete_validate_render_install_remove(
    completed, tmp_path, monkeypatch
):
    out = _invoke("validate", "--skills-dir", completed.parent).stdout
    assert f"{NAME}: ok" in out
    assert "1 skill(s): 1 ok, 0 incomplete, 0 invalid" in out
    assert _invoke("validate", f"./skills/{NAME}").stdout == out

    # the rest of the CLI reads the bundled skills; point it at these instead
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", completed.parent)
    for agent in sorted(ALL_ADAPTERS):
        shown = _invoke("show", NAME, "--agent", agent).stdout
        assert "# Widget Review" in shown, agent
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    _invoke("install", NAME, "--agent", "all", "--agent", "copilot-prompt")
    skill = registry.load_skill(completed, set(ADAPTERS))
    installed = [
        ALL_ADAPTERS[agent].destination(skill, Scope.PROJECT)
        for agent in [*ADAPTERS, "copilot-prompt"]
    ]
    assert all(path.is_file() for path in installed)
    status = _invoke("status", "--agent", "all").stdout
    assert status.count(f"{NAME}  0.1.0 up to date") == len(ADAPTERS)
    _invoke("uninstall", NAME, "--agent", "all", "--agent", "copilot-prompt")
    assert not any(path.exists() for path in installed)


# --- each rule, broken on purpose -------------------------------------------------


def _edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def _problem(report, rule):
    (problem,) = [p for p in report["problems"] if p["rule"] == rule]
    return problem


def test_malformed_metadata(completed):
    _edit(completed / "meta.yaml", "version: 0.1.0", "version: 1.10")
    report = _report("--skills-dir", completed.parent)
    problem = _problem(report, "meta.version")
    assert problem["path"] == f"skills/{NAME}/meta.yaml"
    assert problem["level"] == "error"
    assert "float 1.1" in problem["message"]
    assert "quote" in problem["remediation"]
    assert report["skills"][0]["status"] == "invalid"
    # skill.md is still checked, but nothing that needs the loaded skill
    assert _rules(report) == {"meta.version"}
    assert [s["check"] for s in report["skipped"]][0] == (
        f"rendering and catalog entry of {NAME}"
    )


def test_unparseable_metadata(completed):
    (completed / "meta.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    problem = _problem(_report("--skills-dir", completed.parent), "meta.syntax")
    assert problem["path"] == f"skills/{NAME}/meta.yaml"


def test_unsupported_agent(completed):
    _edit(completed / "meta.yaml", "  - kiro\n", "  - kiro\n  - vscode\n")
    problem = _problem(_report("--skills-dir", completed.parent), "meta.unknown-agent")
    assert "vscode" in problem["message"]
    assert "claude, codex, copilot, cursor and kiro" in problem["remediation"]


def test_legacy_adapter_names_are_not_agents(completed):
    _edit(completed / "meta.yaml", "  - kiro\n", "  - kiro\n  - cursor-rule\n")
    report = _report("--skills-dir", completed.parent)
    assert "follow their agent" in _problem(report, "meta.unknown-agent")["remediation"]


def test_missing_reference(completed):
    _edit(completed / "skill.md", SOURCE, "Grounded in the Widget Guide.")
    report = _report("--skills-dir", completed.parent)
    problem = _problem(report, "references.cited-source")
    assert problem["path"] == f"skills/{NAME}/skill.md"
    assert problem["level"] == "incomplete"
    assert report["skills"][0]["status"] == "incomplete"


def test_superseded_reference(completed):
    _edit(completed / "skill.md", SOURCE, SOURCE + " See ASVS v4.0.3.")
    problem = _problem(
        _report("--skills-dir", completed.parent), "references.superseded"
    )
    assert problem["line"] and "ASVS 5.0" in problem["message"]


def test_missing_section(completed):
    _edit(completed / "skill.md", "\n## Scope\n", "\n## Where to look\n")
    report = _report("--skills-dir", completed.parent)
    problem = _problem(report, "structure.section")
    assert "## Scope" in problem["message"]
    assert problem["path"] == f"skills/{NAME}/skill.md"


def test_reworded_rubric(completed):
    _edit(completed / "skill.md", "readily triggered", "easily triggered")
    problem = _problem(
        _report("--skills-dir", completed.parent), "structure.severity-rubric"
    )
    lines = (completed / "skill.md").read_text(encoding="utf-8").split("\n")
    assert problem["line"] == lines.index("## Output") + 1


def test_heading_must_spell_the_name(completed):
    _edit(completed / "skill.md", "# Widget Review\n", "# Gadget Review\n")
    problem = _problem(_report("--skills-dir", completed.parent), "structure.heading")
    assert problem["line"] == 1


def test_leftover_placeholder_is_located(completed):
    _edit(completed / "skill.md", SOURCE, f"{SOURCE}\n\n{lint.PLACEHOLDER}: more.")
    problem = _problem(_report("--skills-dir", completed.parent), "content.placeholder")
    text = (completed / "skill.md").read_text(encoding="utf-8")
    assert problem["line"] == text.split(lint.PLACEHOLDER)[0].count("\n") + 1


def test_unexpected_file(completed):
    (completed / "notes.txt").write_text("scratch\n", encoding="utf-8")
    problem = _problem(
        _report("--skills-dir", completed.parent), "skill.unexpected-file"
    )
    assert problem["path"] == f"skills/{NAME}/notes.txt"


# YAML must quote it (": "), and Cursor's reader can't undo either quoting
QUOTED = 'Review "key: value" pairs that aren\'t escaped.'


def test_render_failure_names_the_adapter(skills_dir):
    _new(skills_dir, NAME, "--description", QUOTED)
    _complete(skills_dir / NAME)
    problem = _problem(_report("--skills-dir", skills_dir), "render.failed")
    assert "cursor-rule" in problem["message"]
    assert problem["path"] == f"skills/{NAME}/meta.yaml"


def test_catalog_entry_failure(completed, monkeypatch):
    def broken(skill):
        raise OSError("disk on fire")

    monkeypatch.setattr(authoring, "skill_entry", broken)
    problem = _problem(_report("--skills-dir", completed.parent), "catalog.entry")
    assert "disk on fire" in problem["message"]


def test_deprecated_replacement_must_exist(completed):
    meta = completed / "meta.yaml"
    meta.write_text(
        meta.read_text(encoding="utf-8")
        + "deprecated:\n  since: 0.1.0\n  replacement: gone\n  reason: Folded.\n",
        encoding="utf-8",
    )
    problem = _problem(
        _report("--skills-dir", completed.parent), "meta.deprecated-replacement"
    )
    assert "'gone' is not a skill" in problem["message"]


def test_missing_skill_md(completed):
    (completed / "skill.md").unlink()
    report = _report("--skills-dir", completed.parent)
    assert _problem(report, "body.missing")["path"] == f"skills/{NAME}/skill.md"


# --- output --------------------------------------------------------------------


def test_human_output_names_file_rule_and_fix(completed):
    _edit(completed / "skill.md", "\n## Scope\n", "\n## Where to look\n")
    out = _invoke("validate", "--skills-dir", completed.parent, code=1).stdout
    lines = out.splitlines()
    index = next(i for i, line in enumerate(lines) if "[structure.section]" in line)
    assert lines[index].startswith(f"skills/{NAME}/skill.md: error [structure.section]")
    assert lines[index + 1].startswith("    fix: add the section")
    assert f"{NAME}: invalid" in out
    assert out.rstrip().endswith("1 skill(s): 0 ok, 0 incomplete, 1 invalid")


def test_json_is_deterministic_and_sorted(skills_dir):
    _new(skills_dir, "b-review")
    _new(skills_dir, "a-review")
    _edit(skills_dir / "a-review" / "meta.yaml", "version: 0.1.0", "version: 1.10")
    first = _invoke("validate", "--json", "--skills-dir", skills_dir, code=1)
    second = _invoke("validate", "--json", "--skills-dir", skills_dir, code=1)
    assert first.stdout_bytes == second.stdout_bytes
    assert first.stdout_bytes == canonical_json(json.loads(first.stdout)).encode()
    assert b"\r" not in first.stdout_bytes
    data = json.loads(first.stdout)
    assert data["schema_version"] == authoring.REPORT_SCHEMA_VERSION
    assert data["ok"] is False
    assert [s["name"] for s in data["skills"]] == ["a-review", "b-review"]
    keys = [
        (p["skill"], p["path"], p["line"] or 0, p["rule"]) for p in data["problems"]
    ]
    assert keys == sorted(keys)
    for problem in data["problems"]:
        assert set(problem) == {
            "skill",
            "path",
            "line",
            "rule",
            "level",
            "message",
            "remediation",
        }
        assert problem["rule"] in lint.RULES
        assert problem["remediation"]


def test_every_rule_is_documented():
    doc = (ROOT / "docs" / "authoring-skills.md").read_text(encoding="utf-8")
    documented = dict(
        re.findall(r"^\| `([a-z]+\.[a-z-]+)` \| (error|incomplete) \|", doc, re.M)
    )
    assert documented == {rule: spec.level for rule, spec in lint.RULES.items()}


# --- choosing what to validate ------------------------------------------------------


def test_validate_needs_a_skills_directory_outside_a_checkout(skills_dir):
    result = _invoke("validate", code=2)
    assert "--skills-dir" in result.stderr
    result = _invoke("validate", NAME, code=2)
    assert "not inside a skilldeck checkout" in result.stderr


def test_validate_rejects_an_unknown_skill(completed):
    result = _invoke("validate", "--skills-dir", completed.parent, "nope", code=2)
    assert "no skill 'nope' in skills" in result.stderr


def test_validate_suggests_a_path_for_a_local_directory(completed, monkeypatch):
    other = completed.parent.parent / "elsewhere"
    (other / "local").mkdir(parents=True)
    monkeypatch.chdir(other)
    result = _invoke("validate", "--skills-dir", completed.parent, "local", code=2)
    assert "pass ./local" in result.stderr


# --- in a skilldeck checkout ----------------------------------------------------------

FINDING_OUTPUT = textwrap.dedent(
    f"""\
    # Finding output format

    Every review skill (`{NAME}`) reports findings in one shape.

    ## Fields

    | Skill | `classifier` is… | Example |
    | --- | --- | --- |
    | `{NAME}` | the widget concern | `Widget misuse` |
    """
)


def _load(path):
    """Import a checkout script by path, as ``skilldeck validate`` does."""
    saved = sys.path[:]
    name = f"_test_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A minimal skilldeck checkout: this repository's generator and eval
    runner, no skills, and a finding-output doc that lists widget-review."""
    root = tmp_path / "skilldeck"
    for relative in (
        "scripts/build_plugin.py",
        "scripts/_pyproject.py",
        "evals/run_evals.py",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, root / relative)
    (root / "src" / "skilldeck" / "skills").mkdir(parents=True)
    (root / "evals" / "fixtures").mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "finding-output.md").write_text(FINDING_OUTPUT, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "skilldeck"\nversion = "0.3.0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(root)
    # the copied build_plugin.py imports its own _pyproject; keep that copy
    # out of the other tests' way
    monkeypatch.delitem(sys.modules, "_pyproject", raising=False)
    return root


def _plant(fixture_dir):
    """Turn the scaffolded fixture into a planted one."""
    for part in ("base", "change"):
        (fixture_dir / part / "README.md").unlink()
    (fixture_dir / "base" / "widgets.py").write_text(
        "def spin(widget):\n    return widget.spin(speed=1)\n", encoding="utf-8"
    )
    (fixture_dir / "change" / "widgets.py").write_text(
        "def spin(widget):\n    return widget.spin(speed=10**9)\n", encoding="utf-8"
    )
    (fixture_dir / "expected.yaml").write_text(
        f"skill: {NAME}\nplants:\n  - file: widgets.py\n    keywords: [overspeed]\n"
        "max-findings: 2\n",
        encoding="utf-8",
    )


def _regenerate(root):
    build = _load(root / "scripts" / "build_plugin.py")
    build.write(build.generate(root, root / "src" / "skilldeck" / "skills"), root)


def test_checkout_detection(checkout):
    assert authoring.find_checkout(checkout / "src") == authoring.Checkout(
        checkout.resolve()
    )
    assert authoring.checkout_of(checkout / "src" / "skilldeck" / "skills")
    assert authoring.checkout_of(checkout / "docs") is None
    assert authoring.find_checkout(checkout.parent) is None


def test_checkout_lifecycle(checkout, capsys):
    out = _invoke(
        "new", NAME, "--category", "review", "--description", DESCRIPTION
    ).stdout
    skill_dir = checkout / "src" / "skilldeck" / "skills" / NAME
    fixture_dir = checkout / "evals" / "fixtures" / NAME
    assert f"created evals/fixtures/{NAME}/expected.yaml" in out
    assert "scripts/build_plugin.py" in out

    # the fixture skeleton is a valid (clean-diff) fixture, so committing it
    # breaks nothing, but validate still reports what is left to write
    runner = _load(checkout / "evals" / "run_evals.py")
    fixture = runner.load_fixture(fixture_dir)
    assert fixture.skill == NAME and fixture.plants == ()
    assert runner.fixture_layout_problems(fixture) == []

    report = _report()
    assert report["skills"][0]["checkout"] is True
    assert report["skills"][0]["status"] == "incomplete"
    assert _rules(report, "incomplete") == {
        "content.placeholder",
        "references.cited-source",
        "eval.fixture-missing",
    }
    # nothing is generated for the new skill yet
    stale = [p for p in report["problems"] if p["rule"] == "generated.stale"]
    assert f"claude-plugin/skills/{NAME}/SKILL.md" in {p["path"] for p in stale}
    assert all(p["skill"] is None and p["level"] == "error" for p in stale)
    assert _rules(report, "error") == {"generated.stale"}

    _complete(skill_dir)
    _plant(fixture_dir)
    _regenerate(checkout)
    capsys.readouterr()
    clean = _invoke("validate", NAME).stdout
    assert f"{NAME}: ok" in clean

    # an edit without regenerating leaves the generated tree stale
    _edit(skill_dir / "skill.md", SOURCE, SOURCE + " Also see the FAQ.")
    report = _report(NAME)
    assert _rules(report) == {"generated.stale"}
    assert {(p["path"], p["message"]) for p in report["problems"]} >= {
        (f"claude-plugin/skills/{NAME}/SKILL.md", "generated file is out of date"),
        ("src/skilldeck/_content_manifest.json", "generated file is out of date"),
    }
    assert "scripts/build_plugin.py" in report["problems"][0]["remediation"]


def test_validate_is_offline(checkout, monkeypatch):
    # no network and no subprocess (no git, no agent) for any check
    _invoke("new", NAME, "--category", "review")

    def refuse(*args, **kwargs):
        raise AssertionError("validate tried to reach outside the process")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    report = _report(NAME)
    assert "generated.stale" in _rules(report)
    assert "eval.fixture-missing" in _rules(report)


def test_checkout_missing_eval_fixture(checkout):
    _invoke("new", NAME, "--category", "review", "--no-eval-fixture")
    assert not (checkout / "evals" / "fixtures" / NAME).exists()
    problem = _problem(_report(NAME), "eval.fixture-missing")
    assert problem["message"] == f"no eval fixture exercises {NAME}"
    assert problem["path"] == f"evals/fixtures/{NAME}"
    assert f"add evals/fixtures/{NAME}/" in problem["remediation"]


def test_checkout_invalid_eval_fixture(checkout):
    _invoke("new", NAME, "--category", "review")
    fixture_dir = checkout / "evals" / "fixtures" / NAME
    _edit(fixture_dir / "expected.yaml", "max-findings: 0", "max-findings: 0\nextra: 1")
    problem = _problem(_report(NAME), "eval.fixture-invalid")
    assert problem["path"] == f"evals/fixtures/{NAME}/expected.yaml"
    assert "unknown key(s) ['extra']" in problem["message"]


def test_checkout_new_refuses_an_existing_fixture(checkout):
    (checkout / "evals" / "fixtures" / NAME).mkdir()
    result = _invoke("new", NAME, "--category", "review", code=2)
    assert "--no-eval-fixture" in result.stderr
    assert not (checkout / "src" / "skilldeck" / "skills" / NAME).exists()


def test_checkout_skill_missing_from_the_finding_output_doc(checkout):
    _invoke("new", "other-review", "--category", "review")
    problem = _problem(_report("other-review"), "docs.finding-output")
    assert problem["path"] == "docs/finding-output.md"


def test_bundled_skills_validate_clean():
    # the real checkout: every bundled skill passes every check, placeholders
    # and generated output included (the same rules the tests above break)
    skills_dir = ROOT / "src" / "skilldeck" / "skills"
    report = authoring.validate(authoring.skill_dirs(skills_dir), base=ROOT)
    assert report.problems == [], authoring.format_report(report)
    assert report.skipped == []
    assert {skill.status for skill in report.skills} == {"ok"}
    assert all(skill.checkout for skill in report.skills)
