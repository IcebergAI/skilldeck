"""Structure checks for the golden-diff eval fixtures.

The eval runner itself (``evals/run_evals.py``) calls a paid agent and is run
manually; these tests keep the fixtures healthy in CI without any API calls:
every fixture must load, target a bundled skill, plant its defect inside the
reviewed diff, and produce a working git repo.
"""

import importlib.util
import shlex
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
    # A skill may have several fixtures: the directory is either the skill name
    # or the skill name plus a "-<variant>" suffix (e.g. a GitLab variant).
    assert FIXTURE_DIRS, "no eval fixtures found"
    for path in FIXTURE_DIRS:
        fixture = run_evals.load_fixture(path)
        assert path.name == fixture.skill or path.name.startswith(fixture.skill + "-")


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
        source = (path / "change" / plant.file).read_text(encoding="utf-8")
        assert 1 <= plant.lines[0] <= plant.lines[1] <= len(source.splitlines())
        assert plant.min_severity in run_evals.SEVERITIES
        for keyword in plant.keywords:
            assert keyword.lower() not in source.lower(), (
                f"keyword {keyword!r} can be copied from {plant.file}"
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
    # the skill is installed for claude at project scope
    assert (repo / ".claude" / "skills" / fixture.skill / "SKILL.md").is_file()


def test_score_detects_hits_and_false_positive_pressure():
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    plant = fixture.plants[0]
    hit = (
        f"- **[critical] Secret in log** — `{plant.file}:14`\n"
        "  **Issue:** credential leak.\n  **Fix:** redact the token.\n"
    )
    problems, passed = run_evals.score(fixture, hit)
    assert passed, problems

    problems, passed = run_evals.score(fixture, "Reviewed. Clean.")
    assert not passed and any("missed plant" in p for p in problems)

    noisy = hit * (fixture.max_findings + 1)
    problems, passed = run_evals.score(fixture, noisy)
    assert not passed and any("too many findings" in p for p in problems)


@pytest.mark.parametrize(
    "report",
    [
        "auth/session.py: no secrets logged, clean",
        "- **[high] Secret** — `other/session.py:14`\n"
        "  **Issue:** credential leak.\n  **Fix:** redact.\n",
        "- **[high] Secret** — `auth/session.py:1`\n"
        "  **Issue:** credential leak.\n  **Fix:** redact.\n",
        "- **[high] Secret** — `auth/session.py:14`\n"
        "  **Issue:** clean.\n  **Fix:** none.\n\ncredential leak elsewhere",
        "- **[low] Secret** — `auth/session.py:14`\n"
        "  **Issue:** credential leak.\n  **Fix:** redact.\n",
    ],
)
def test_wrong_reports_do_not_pass(report):
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    assert not run_evals.score(fixture, report)[1]


@pytest.mark.parametrize("bullet", ["*", "+", "1.", "1)"])
def test_all_bullet_styles_count_toward_cap(bullet):
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    report = (
        f"{bullet} **[high] Secret** — `auth/session.py:14`\n"
        "  **Issue:** credential leak.\n  **Fix:** redact.\n"
    )
    problems, passed = run_evals.score(fixture, report * (fixture.max_findings + 1))
    assert not passed and any("too many findings" in p for p in problems)


def test_agent_stderr_is_not_a_report(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, "report", "diagnostic"),
    )
    assert run_evals.run_agent("agent", "prompt", tmp_path, 10) == "report"


@pytest.mark.parametrize(
    "keyword,wrong,right",
    [
        ("git", "github", "git source"),
        ("state", "statement", "missing state"),
        ("lock", "block lockfile", "table lock"),
    ],
)
def test_keywords_have_word_boundaries(keyword, wrong, right):
    assert not run_evals.keyword_matches(keyword, wrong)
    assert run_evals.keyword_matches(keyword, right)


def finding(file, lines, issue, severity="high", bullet="-"):
    return (
        f"{bullet} **[{severity}] defect** — `{file}:{lines}`\n"
        f"  **Issue:** {issue}\n  **Fix:** fix the defect.\n"
    )


@pytest.mark.parametrize("bullet", ["-", "*", "+", "1.", "1)"])
def test_every_fixture_has_a_valid_report(bullet):
    for path in FIXTURE_DIRS:
        fixture = run_evals.load_fixture(path)
        report = "\n".join(
            finding(
                p.file, f"{p.lines[0]}-{p.lines[1]}", p.keywords[0], "critical", bullet
            )
            for p in fixture.plants
        )
        problems, passed = run_evals.score(fixture, report)
        assert passed, (path, problems)


def test_two_plants_in_one_file_need_distinct_findings():
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "ci-workflow-review-gitlab")
    one = finding(".gitlab-ci.yml", "14-24", "untrusted input and host access")
    assert not run_evals.score(fixture, one)[1]
    two = finding(".gitlab-ci.yml", "24", "untrusted input")
    # The first finding must be reassigned so the second can match plant 1.
    assert run_evals.score(fixture, one + two)[1]


@pytest.mark.parametrize(
    "report",
    [
        "",
        "No findings.",
        "```\n" + finding("auth/session.py", "14", "credential leak") + "```",
        finding("auth/session.py", "0", "credential leak"),
        finding("auth/session.py", "15-14", "credential leak"),
        finding("auth/session.py", "14", "credential leak", "urgent"),
        finding("auth/session.py", "14", "credential leak")
        + "- **[high] malformed**\n",
        "- **[high] defect** — `auth/session.py:14`\n  **Issue:** credential leak\n",
        finding("auth/session.py", "14", "clean")
        + finding("other.py", "14", "credential leak"),
        finding("auth/session.py", "14", "credential leak")
        + "  "
        + finding("other.py", "1", "extra finding"),
    ],
)
def test_missing_or_malformed_reports_fail_closed(report):
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    assert not run_evals.score(fixture, report)[1]


def test_agent_nonzero_exit_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            [], 1, "valid-looking report", "failure"
        ),
    )
    with pytest.raises(run_evals.AgentError, match="status 1"):
        run_evals.run_agent("agent", "prompt", tmp_path, 10)


def test_agent_timeout_is_an_error(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("agent", 10)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(run_evals.AgentError, match="timed out"):
        run_evals.run_agent("agent", "prompt", tmp_path, 10)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_real_child_process_output_and_failure(tmp_path, exit_code):
    script = tmp_path / "agent.py"
    script.write_text(
        f"import sys\nprint('stdout report')\n"
        f"print('stderr diagnostic', file=sys.stderr)\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    command = shlex.join([sys.executable, str(script)])
    if exit_code:
        with pytest.raises(run_evals.AgentError, match="status 7"):
            run_evals.run_agent(command, "prompt", tmp_path, 10)
    else:
        assert run_evals.run_agent(command, "prompt", tmp_path, 10) == "stdout report\n"


def test_minimum_severity_defaults_to_low(tmp_path):
    (tmp_path / "expected.yaml").write_text(
        "skill: logging\nplants:\n  - file: auth/session.py\n"
        "    lines: [14, 14]\n    keywords: [secret]\nmax-findings: 2\n",
        encoding="utf-8",
    )
    fixture = run_evals.load_fixture(tmp_path)
    assert fixture.plants[0].min_severity == "low"
    assert run_evals.score(fixture, finding("auth/session.py", "14", "secret", "low"))[
        1
    ]


def test_main_records_agent_failure_and_returns_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["run_evals.py", "--skill", "logging"])
    monkeypatch.setattr(run_evals.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
    monkeypatch.setattr(run_evals, "prepare_repo", lambda *a: tmp_path)

    def fail(*args):
        raise run_evals.AgentError("agent exited with status 7")

    monkeypatch.setattr(run_evals, "run_agent", fail)
    assert run_evals.main() == 1
    assert "ERROR logging" in capsys.readouterr().out
    assert "status 7" in (tmp_path / "agent-error.txt").read_text()
    assert not (tmp_path / "report.txt").exists()
