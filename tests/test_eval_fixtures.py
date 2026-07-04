"""Structure checks for the golden-diff eval fixtures.

The eval runner itself (``evals/run_evals.py``) calls a paid agent and is run
manually; these tests keep the fixtures healthy in CI without any API calls:
every fixture must load, target a bundled skill, plant its defect inside the
reviewed diff, and produce a working git repo.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "evals" / "run_evals.py"
_spec = importlib.util.spec_from_file_location("run_evals", _SCRIPT)
assert _spec and _spec.loader
run_evals = importlib.util.module_from_spec(_spec)
# dataclass field resolution looks the module up in sys.modules
sys.modules["run_evals"] = run_evals
_spec.loader.exec_module(run_evals)

FIXTURE_DIRS = sorted(p for p in run_evals.FIXTURES.iterdir() if p.is_dir())


def _bundled_skill_names():
    from skilldeck.adapters import ADAPTERS
    from skilldeck.registry import discover_skills

    return {s.name for s in discover_skills(known_agents=set(ADAPTERS))}


def test_every_fixture_dir_is_named_for_its_skill():
    assert FIXTURE_DIRS, "no eval fixtures found"
    for path in FIXTURE_DIRS:
        fixture = run_evals.load_fixture(path)
        assert fixture.skill == path.name


@pytest.mark.parametrize("path", FIXTURE_DIRS, ids=lambda p: p.name)
def test_fixture_is_well_formed(path):
    fixture = run_evals.load_fixture(path)
    assert fixture.skill in _bundled_skill_names()
    assert (path / "base").is_dir()
    assert (path / "change").is_dir()
    assert fixture.plants, "fixture has no plants"
    assert fixture.max_findings > 0
    for plant in fixture.plants:
        assert (path / "change" / plant.file).is_file(), (
            f"plant file {plant.file} not in change/"
        )
        assert plant.keywords


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
    # the skill is installed for claude at project scope
    assert (repo / ".claude" / "skills" / fixture.skill / "SKILL.md").is_file()


def test_score_detects_hits_and_false_positive_pressure():
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    plant = fixture.plants[0]
    hit = f"- **[critical] Secret in log** — `{plant.file}:12`\n"
    problems, passed = run_evals.score(fixture, hit)
    assert passed, problems

    problems, passed = run_evals.score(fixture, "Reviewed. Clean.")
    assert not passed and any("missed plant" in p for p in problems)

    noisy = hit + "- **[low] x** — `y:1`\n" * fixture.max_findings
    problems, passed = run_evals.score(fixture, noisy)
    assert not passed and any("too many findings" in p for p in problems)
