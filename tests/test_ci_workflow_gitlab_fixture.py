"""Guards for the GitLab variant of the ci-workflow-review eval fixture (#101).

The fixture once planted a quoted ``echo "$CI_MERGE_REQUEST_TITLE"`` -- safe on
GitLab, where CI/CD variables reach the shell as environment variables and are
expanded once -- and scored it as injection using a keyword copied from the
planted line. The plant must be a real re-evaluation sink, and the keywords
must name the finding rather than echo the code or match the other plant.
"""

import dataclasses
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = _ROOT / "evals" / "fixtures" / "ci-workflow-review-gitlab"
EXPECTED = yaml.safe_load((FIXTURE / "expected.yaml").read_text(encoding="utf-8"))


def _load_run_evals():
    if "run_evals" in sys.modules:
        return sys.modules["run_evals"]
    spec = importlib.util.spec_from_file_location(
        "run_evals", _ROOT / "evals" / "run_evals.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclass field resolution looks the module up in sys.modules
    sys.modules["run_evals"] = module
    spec.loader.exec_module(module)
    return module


run_evals = _load_run_evals()

# GitLab variables whose value an MR author chooses (MR text, branch names, and
# the commit text a merge carries onto the default branch)
ATTACKER_VARS = (
    "CI_COMMIT_TITLE",
    "CI_COMMIT_MESSAGE",
    "CI_COMMIT_DESCRIPTION",
    "CI_COMMIT_AUTHOR",
    "CI_COMMIT_REF_NAME",
    "CI_COMMIT_BRANCH",
    "CI_MERGE_REQUEST_TITLE",
    "CI_MERGE_REQUEST_DESCRIPTION",
    "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME",
)
ATTACKER_REF = re.compile(r"\$\{?(?:" + "|".join(ATTACKER_VARS) + r")\b")
# break out of each quoting context the value could land in
PAYLOADS = ("$(touch pwned)", "'$(touch pwned)'", '"$(touch pwned)"')

# a realistic finding for each plant, keyed by the plant's first keyword; each
# must score its own plant and must not score the other one
FINDINGS = {
    "injection": (
        "announce-release passes the commit title to `sh -c`, which re-parses "
        "it as shell: command substitution in an MR title or source branch "
        "runs with the job's protected variables. Pass it as a positional "
        "parameter instead."
    ),
    "docker-in-docker": (
        "build-image sends merge request pipelines to a privileged "
        "docker-in-docker runner, so any MR author can execute arbitrary "
        "commands with root access on the runner host (container escape)."
    ),
}


def _script_lines():
    ci = yaml.safe_load((FIXTURE / "change" / ".gitlab-ci.yml").read_text())
    return [
        line
        for job in ci.values()
        if isinstance(job, dict)
        for line in job.get("script", [])
    ]


def _runs_attacker_text(line, workdir):
    """Run a ``script:`` line as the runner's shell would, with every
    attacker-controlled variable set to a payload, and report whether any
    payload executed."""
    marker = workdir / "pwned"
    for payload in PAYLOADS:
        env = {"PATH": os.environ["PATH"], **dict.fromkeys(ATTACKER_VARS, payload)}
        subprocess.run(
            ["sh", "-c", line], cwd=workdir, env=env, capture_output=True, timeout=10
        )
        if marker.exists():
            marker.unlink()
            return True
    return False


needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")


@pytest.mark.parametrize("plant", EXPECTED["plants"], ids=lambda p: p["keywords"][0])
def test_plant_keywords_do_not_appear_in_the_planted_file(plant):
    code = (FIXTURE / "change" / plant["file"]).read_text(encoding="utf-8").lower()
    copied = [k for k in plant["keywords"] if k.lower() in code]
    assert not copied, f"keywords copied from {plant['file']}: {copied}"


@pytest.mark.parametrize(
    "index",
    range(len(EXPECTED["plants"])),
    ids=[p["keywords"][0] for p in EXPECTED["plants"]],
)
def test_a_report_of_the_other_plant_does_not_score_this_one(index):
    # a keyword that a finding about the other plant would contain lets a
    # report that misses this plant pass
    fixture = run_evals.load_fixture(FIXTURE)
    plant = fixture.plants[index]
    only_this = dataclasses.replace(fixture, plants=(plant,))
    opener = "Reviewed main..change; I evaluated each changed job's triggers.\n"

    def report(key):
        return opener + f"- **[high] CICD-SEC-4** — `{plant.file}:1` {FINDINGS[key]}\n"

    own = plant.keywords[0]
    assert run_evals.score(only_this, report(own))[1], f"{own} finding misses"
    for other in FINDINGS.keys() - {own}:
        assert not run_evals.score(only_this, report(other))[1], (
            f"a {other} finding also scores the {own} plant"
        )


@needs_sh
def test_injection_plant_runs_attacker_text(tmp_path):
    lines = [line for line in _script_lines() if ATTACKER_REF.search(line)]
    assert any(_runs_attacker_text(line, tmp_path) for line in lines), (
        "no script line executes MR/commit text: the injection plant must pass "
        "it through a re-evaluating sink (eval, sh -c, bash -c); a quoted "
        "expansion is not injectable"
    )


@needs_sh
@pytest.mark.parametrize(
    "line",
    [
        'echo "Building for MR: $CI_MERGE_REQUEST_TITLE"',
        'sh -c \'./ci/notify-chat.sh "Released $1"\' _ "$CI_COMMIT_TITLE"',
    ],
    ids=["quoted-expansion", "positional-parameter"],
)
def test_the_skills_safe_forms_do_not_run_attacker_text(line, tmp_path):
    # the harness above must not flag what the skill calls safe
    assert not _runs_attacker_text(line, tmp_path)
