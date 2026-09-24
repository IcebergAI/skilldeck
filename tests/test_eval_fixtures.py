"""Structure checks for the golden-diff eval fixtures.

The eval runner itself (``evals/run_evals.py``) calls a paid agent and is run
manually; these tests keep the fixtures healthy in CI without any API calls:
every fixture must load, target a bundled skill, plant its defects inside the
reviewed diff with keywords that describe the defect rather than echo the code,
and produce a working git repo. The scorer is covered by test_eval_scoring.py.
"""

import subprocess

import pytest
import run_evals  # loaded from evals/run_evals.py by conftest.py

FIXTURE_DIRS = sorted(p for p in run_evals.FIXTURES.iterdir() if p.is_dir())


def _bundled_skill_names():
    from skilldeck.adapters import ADAPTERS
    from skilldeck.registry import discover_skills

    return {s.name for s in discover_skills(known_agents=set(ADAPTERS))}


def test_every_fixture_dir_is_named_for_its_skill():
    # A skill may have several fixtures: the directory is either the skill name
    # or the skill name plus a "-<variant>" suffix (e.g. a GitLab variant).
    assert FIXTURE_DIRS, "no eval fixtures found"
    for path in FIXTURE_DIRS:
        fixture = run_evals.load_fixture(path)
        assert path.name == fixture.skill or path.name.startswith(fixture.skill + "-")


def test_there_is_a_clean_diff_fixture():
    # false-positive pressure needs at least one change that should pass clean
    assert any(not run_evals.load_fixture(p).plants for p in FIXTURE_DIRS)


@pytest.mark.parametrize("path", FIXTURE_DIRS, ids=lambda p: p.name)
def test_fixture_is_well_formed(path):
    fixture = run_evals.load_fixture(path)
    assert fixture.skill in _bundled_skill_names()
    assert (path / "base").is_dir()
    assert (path / "change").is_dir()
    for plant in fixture.plants:
        assert (path / "change" / plant.file).is_file(), (
            f"plant file {plant.file} not in change/"
        )
    if not fixture.plants:
        # a clean-diff fixture's max-findings is its false-positive tolerance
        assert fixture.max_findings <= 2, "keep a clean fixture's tolerance small"


@pytest.mark.parametrize("path", FIXTURE_DIRS, ids=lambda p: p.name)
def test_plant_keywords_describe_the_defect_not_the_code(path):
    # A keyword copied from the planted code (a variable, an event name, a
    # CIDR) is satisfied by any report that quotes the line, whether or not it
    # identified the defect. Same whole-word matching as the scorer.
    fixture = run_evals.load_fixture(path)
    for plant in fixture.plants:
        code = (path / "change" / plant.file).read_text(encoding="utf-8")
        echoed = [k for k in plant.keywords if run_evals.mentions(code, k)]
        assert not echoed, (
            f"{plant.file}: keyword(s) {echoed} appear verbatim in the planted "
            "code; keywords must describe the defect, not echo the code"
        )


@pytest.mark.parametrize("path", FIXTURE_DIRS, ids=lambda p: p.name)
def test_fixture_builds_a_repo_with_the_plant_in_the_diff(path, tmp_path):
    fixture = run_evals.load_fixture(path)
    repo = run_evals.prepare_repo(fixture, tmp_path)
    diff = subprocess.run(
        ["git", "diff", "--name-only", "main...change"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    changed = set(diff.split())
    assert changed, "change branch has an empty diff"
    for plant in fixture.plants:
        assert plant.file in changed, f"plant {plant.file} is not part of the diff"
    # the skill is installed for claude at project scope by default
    assert (repo / ".claude" / "skills" / fixture.skill / "SKILL.md").is_file()
