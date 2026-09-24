"""Guards for the GitLab variant of the ci-workflow-review eval fixture (#101).

The fixture once planted a quoted ``echo "$CI_MERGE_REQUEST_TITLE"`` -- safe on
GitLab, where CI/CD variables reach the shell as environment variables and are
expanded once -- and scored it as injection using a keyword copied from the
planted line. The plant must be a real re-evaluation sink, and the keywords
must name the finding rather than echo the code.
"""

import re
from pathlib import Path

import pytest
import yaml

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "evals"
    / "fixtures"
    / "ci-workflow-review-gitlab"
)
EXPECTED = yaml.safe_load((FIXTURE / "expected.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("plant", EXPECTED["plants"], ids=lambda p: p["keywords"][0])
def test_plant_keywords_do_not_appear_in_the_planted_file(plant):
    code = (FIXTURE / "change" / plant["file"]).read_text(encoding="utf-8").lower()
    copied = [k for k in plant["keywords"] if k.lower() in code]
    assert not copied, f"keywords copied from {plant['file']}: {copied}"


def test_injection_plant_re_evaluates_attacker_controlled_text():
    ci = yaml.safe_load((FIXTURE / "change" / ".gitlab-ci.yml").read_text())
    lines = [
        line
        for job in ci.values()
        if isinstance(job, dict)
        for line in job.get("script", [])
    ]
    sink = re.compile(r"\b(eval|sh -c|bash -c)\b.*\$\{?CI_(COMMIT|MERGE_REQUEST)_")
    assert any(sink.search(line) for line in lines), (
        "the injection plant must pass MR/commit text through a re-evaluating "
        "sink (eval, sh -c, bash -c); a quoted expansion is not injectable"
    )
