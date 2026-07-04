#!/usr/bin/env python3
"""Run the golden-diff skill evals against a real agent.

Each fixture under ``evals/fixtures/<skill>/`` is a tiny repository with a
planted defect:

* ``base/``          -- the pre-change tree (committed to ``main``)
* ``change/``        -- files overlaid on a ``change`` branch (the diff under
  review; contains the plant)
* ``expected.yaml``  -- which skill to install, the planted defects the report
  must find, and a cap on total findings (false-positive pressure)

For every fixture the runner builds the git repo in a temp dir, installs the
skill for Claude at project scope, invokes the agent inside the repo, and
scores the report: every plant must be mentioned (file + at least one keyword)
and the finding count must stay under ``max_findings``.

This calls a real agent and costs real money -- it is run manually (e.g.
before a release), not in CI. CI only validates fixture structure, via
``tests/test_eval_fixtures.py``.

Usage:
    python evals/run_evals.py                       # all fixtures, claude CLI
    python evals/run_evals.py --skill logging       # one fixture
    python evals/run_evals.py --agent-cmd 'claude -p {prompt}'
    python evals/run_evals.py --keep                # keep temp repos to inspect
"""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skilldeck.adapters import ADAPTERS  # noqa: E402
from skilldeck.registry import discover_skills  # noqa: E402
from skilldeck.targets import Scope  # noqa: E402

FIXTURES = ROOT / "evals" / "fixtures"
DEFAULT_AGENT_CMD = "claude -p {prompt}"
DEFAULT_PROMPT = (
    "Review the pending changes on the current branch (the diff against main) "
    "using the {skill} skill installed in .claude/skills. Output the findings "
    "report exactly as the skill specifies."
)
# one finding bullet as the skills' Output sections specify: "- **[severity]"
FINDING_RE = re.compile(r"^\s*-\s+\*\*\[", re.MULTILINE)


@dataclass(frozen=True)
class Plant:
    file: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Fixture:
    path: Path
    skill: str
    plants: tuple[Plant, ...]
    max_findings: int


def load_fixture(path: Path) -> Fixture:
    expected = yaml.safe_load((path / "expected.yaml").read_text(encoding="utf-8"))
    return Fixture(
        path=path,
        skill=expected["skill"],
        plants=tuple(
            Plant(file=p["file"], keywords=tuple(p["keywords"]))
            for p in expected["plants"]
        ),
        max_findings=int(expected["max-findings"]),
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=evals", "-c", "user.email=evals@localhost", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def prepare_repo(fixture: Fixture, workdir: Path) -> Path:
    """Materialize the fixture as a git repo with a ``change`` branch."""
    repo = workdir / fixture.path.name
    shutil.copytree(fixture.path / "base", repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "change")
    shutil.copytree(fixture.path / "change", repo, dirs_exist_ok=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change under review")

    skill = next(
        s
        for s in discover_skills(known_agents=set(ADAPTERS))
        if s.name == fixture.skill
    )
    ADAPTERS["claude"].install(skill, Scope.PROJECT, project_root=repo)
    return repo


def run_agent(agent_cmd: str, prompt: str, repo: Path, timeout: int) -> str:
    cmd = [part.replace("{prompt}", prompt) for part in shlex.split(agent_cmd)]
    try:
        result = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise SystemExit(
            f"error: agent command not found: {cmd[0]!r} — install it or pass "
            "--agent-cmd"
        ) from None
    except subprocess.TimeoutExpired:
        return f"(agent timed out after {timeout}s)"
    return result.stdout + result.stderr


def score(fixture: Fixture, report: str) -> tuple[list[str], bool]:
    """Return (problems, passed) for one fixture's report."""
    problems = []
    lowered = report.lower()
    for plant in fixture.plants:
        file_hit = Path(plant.file).name.lower() in lowered
        keyword_hit = any(k.lower() in lowered for k in plant.keywords)
        if not (file_hit and keyword_hit):
            problems.append(
                f"missed plant: {plant.file} "
                f"(need the file and one of {list(plant.keywords)})"
            )
    findings = len(FINDING_RE.findall(report))
    if findings > fixture.max_findings:
        problems.append(
            f"too many findings: {findings} > max {fixture.max_findings} "
            "(false-positive pressure)"
        )
    return problems, not problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", help="run only this fixture")
    parser.add_argument(
        "--agent-cmd",
        default=DEFAULT_AGENT_CMD,
        help="agent command; {prompt} is substituted (default: %(default)r)",
    )
    parser.add_argument(
        "--timeout", type=int, default=600, help="per-fixture agent timeout (s)"
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep the temp repos for inspection"
    )
    args = parser.parse_args()

    fixtures = [
        load_fixture(path)
        for path in sorted(FIXTURES.iterdir())
        if path.is_dir() and (args.skill is None or path.name == args.skill)
    ]
    if not fixtures:
        print(f"error: no fixture named {args.skill!r}", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="skilldeck-evals-"))
    print(f"work dir: {workdir}\n")
    failed = 0
    for fixture in fixtures:
        repo = prepare_repo(fixture, workdir)
        prompt = DEFAULT_PROMPT.format(skill=fixture.skill)
        report = run_agent(args.agent_cmd, prompt, repo, args.timeout)
        (repo / "report.txt").write_text(report, encoding="utf-8")
        problems, passed = score(fixture, report)
        status = "PASS" if passed else "FAIL"
        findings = len(FINDING_RE.findall(report))
        print(f"{status}  {fixture.skill}  ({findings} findings)")
        for problem in problems:
            print(f"      {problem}")
        failed += not passed

    print(f"\n{len(fixtures) - failed}/{len(fixtures)} fixtures passed")
    if args.keep or failed:
        print(f"reports kept in {workdir}")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
