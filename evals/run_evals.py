#!/usr/bin/env python3
"""Run the golden-diff skill evals against a real agent.

Each fixture under ``evals/fixtures/<skill>[-<variant>]/`` is a tiny repository
with planted defects (or, for a clean-diff fixture, none):

* ``base/``          -- the pre-change tree (committed to ``main``)
* ``change/``        -- files overlaid on a ``change`` branch (the diff under
  review; contains the plants)
* ``expected.yaml``  -- which skill to install, the planted defects the report
  must find, and a cap on total findings (false-positive pressure)

For every fixture the runner builds the git repo in a temp dir, installs the
skill through a skilldeck adapter at project scope, invokes the agent inside
the repo, and scores its stdout. The report is parsed into individual findings
(the shared shape in ``docs/finding-output.md``); each plant must be matched by
its own finding that names the plant's file and one of its keywords (whole
words, case-insensitive) at or above its optional ``min-severity``, and the
finding count must not exceed ``max-findings``.

This calls a real agent and costs real money -- it is run manually (e.g.
before a release), not in CI. CI only validates fixture structure and the
scorer, via ``tests/test_eval_fixtures.py`` and ``tests/test_eval_scoring.py``.

Usage:
    python evals/run_evals.py                       # all fixtures, claude CLI
    python evals/run_evals.py --skill logging       # one skill's fixtures
    python evals/run_evals.py --repeat 5            # pass rate per fixture
    python evals/run_evals.py --agent-cmd 'claude -p {prompt}'
    python evals/run_evals.py --adapter codex --agent-cmd 'codex exec {prompt}'
    python evals/run_evals.py --keep                # keep temp repos to inspect
"""

from __future__ import annotations

import argparse
import functools
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skilldeck.adapters import ADAPTERS  # noqa: E402
from skilldeck.registry import Skill, discover_skills  # noqa: E402
from skilldeck.targets import Scope  # noqa: E402

FIXTURES = ROOT / "evals" / "fixtures"
DEFAULT_ADAPTER = "claude"
DEFAULT_AGENT_CMD = "claude -p {prompt}"
DEFAULT_PROMPT = (
    "Review the pending changes on the current branch (the diff against main) "
    "using the {skill} skill installed at {skill_path}. Output the findings "
    "report exactly as the skill specifies."
)

#: the finding severity scale from docs/finding-output.md, lowest first
SEVERITIES = ("low", "medium", "high", "critical")

# A finding opens with a list marker ("-", "*", "1." or "1)") followed by the
# "**[severity]" marker of the shared finding format (see parse_findings for
# where it ends).
FINDING_START_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:[-*]|\d+[.)])[ \t]+\*\*\[(?P<severity>[^\]\n]*)\]"
)
HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}(?:[ \t]|$)")
# a thematic break (---, ***, ___) or a setext heading underline (===)
BREAK_RE = re.compile(
    r"^[ \t]{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|=+[ \t]*)$"
)
LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]|\d+[.)])(?:[ \t]|$)")
# the finding's own Issue/Fix lines, which some reports leave unindented
FIELD_RE = re.compile(
    r"^[ \t]*(?:\*\*|__)?(?:Issue|Fix)(?:\*\*|__)?[ \t]*:", re.IGNORECASE
)
# an opening code fence: 3+ backticks (with no backtick after them, so a line
# that starts with ```inline code``` isn't one) or 3+ tildes
FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}(?=[^`]*$)|~{3,})")
# a list item led by a severity that isn't the "**[severity]" marker, e.g.
# "1. [high] ..." or "- **High** — ...": a finding the parser can't count
DRIFTED_FINDING_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+[*_\[(]*(?:critical|high|medium|low)"
    r"(?:\]|\)|\*\*|__|:|[ \t]+[—–-])",
    re.IGNORECASE,
)

_FIXTURE_KEYS = frozenset({"skill", "plants", "max-findings"})
_PLANT_KEYS = frozenset({"file", "keywords", "min-severity", "locators"})
_PLANT_REQUIRED = frozenset({"file", "keywords"})


class FixtureError(ValueError):
    """An ``expected.yaml`` that doesn't match the fixture schema."""


@dataclass(frozen=True)
class Plant:
    file: str
    keywords: tuple[str, ...]
    min_severity: str | None = None
    #: extra terms that place a finding at this plant when the skill's
    #: location slot is not a file path (e.g. dependency-review's package name)
    locators: tuple[str, ...] = ()

    @property
    def locations(self) -> tuple[str, ...]:
        """Terms any one of which ties a finding to this plant's location."""
        basename = Path(self.file).name
        return tuple(dict.fromkeys((self.file, basename, *self.locators)))


@dataclass(frozen=True)
class Fixture:
    path: Path
    skill: str
    plants: tuple[Plant, ...]
    max_findings: int

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Finding:
    #: the text inside ``**[...]``, lower-cased -- normally one of SEVERITIES
    severity: str
    text: str


@dataclass(frozen=True)
class AgentRun:
    stdout: str
    stderr: str
    #: None when the agent was killed for exceeding ``timeout``
    returncode: int | None
    timeout: int


# -- fixture loading ---------------------------------------------------------


def _check_keys(
    where: str,
    mapping: dict[object, object],
    allowed: frozenset[str],
    required: frozenset[str],
) -> None:
    unknown = sorted(str(k) for k in mapping if k not in allowed)
    if unknown:
        raise FixtureError(
            f"{where}: unknown key(s) {unknown}; allowed: {sorted(allowed)}"
        )
    missing = sorted(required - set(map(str, mapping)))
    if missing:
        raise FixtureError(f"{where}: missing required key(s) {missing}")


def _string(where: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{where}: expected a non-empty string, got {value!r}")
    return value.strip()


def _strings(where: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FixtureError(f"{where}: expected a non-empty list of strings")
    return tuple(_string(f"{where}[{i}]", item) for i, item in enumerate(value))


def _load_plant(where: str, raw: object) -> Plant:
    if not isinstance(raw, dict):
        raise FixtureError(f"{where}: expected a mapping, got {raw!r}")
    _check_keys(where, raw, _PLANT_KEYS, _PLANT_REQUIRED)
    min_severity = None
    if "min-severity" in raw:
        min_severity = raw["min-severity"]
        if min_severity not in SEVERITIES:
            raise FixtureError(
                f"{where}: min-severity must be one of {list(SEVERITIES)}, "
                f"got {min_severity!r}"
            )
    return Plant(
        file=_string(f"{where}.file", raw["file"]),
        keywords=_strings(f"{where}.keywords", raw["keywords"]),
        min_severity=str(min_severity) if min_severity is not None else None,
        locators=(
            _strings(f"{where}.locators", raw["locators"]) if "locators" in raw else ()
        ),
    )


def load_fixture(path: Path) -> Fixture:
    """Load and validate ``path/expected.yaml``; raise FixtureError if invalid."""
    source = path / "expected.yaml"
    try:
        expected = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FixtureError(f"{source}: {exc}") from exc
    if not isinstance(expected, dict):
        raise FixtureError(f"{source}: expected a YAML mapping")
    _check_keys(str(source), expected, _FIXTURE_KEYS, _FIXTURE_KEYS)

    raw_plants = expected["plants"]
    if not isinstance(raw_plants, list):
        raise FixtureError(f"{source}: plants must be a list ([] for a clean diff)")
    plants = tuple(
        _load_plant(f"{source}: plants[{i}]", raw) for i, raw in enumerate(raw_plants)
    )
    max_findings = expected["max-findings"]
    # bool is an int subclass; `max-findings: yes` is a typo, not a number
    if (
        not isinstance(max_findings, int)
        or isinstance(max_findings, bool)
        or max_findings < 0
    ):
        raise FixtureError(
            f"{source}: max-findings must be a non-negative integer, "
            f"got {max_findings!r}"
        )
    if max_findings < len(plants):
        raise FixtureError(
            f"{source}: max-findings ({max_findings}) is below the number of "
            f"plants ({len(plants)}), so no report could pass"
        )
    return Fixture(
        path=path,
        skill=_string(f"{source}: skill", expected["skill"]),
        plants=plants,
        max_findings=max_findings,
    )


# -- report parsing and scoring ----------------------------------------------


def _width(indent: str) -> int:
    return len(indent.expandtabs(4))


def _indent_of(line: str) -> int:
    return _width(line[: len(line) - len(line.lstrip(" \t"))])


def _opens_fence(line: str) -> tuple[str, int] | None:
    """(char, length) of the code fence ``line`` opens, if it opens one."""
    match = FENCE_RE.match(line)
    return None if match is None else (match["fence"][0], len(match["fence"]))


def _closes_fence(line: str, fence: tuple[str, int]) -> bool:
    # CommonMark: only a run of the same character, at least as long as the
    # opening one and with nothing after it, closes a fence
    char, length = fence
    run = line.strip()
    return len(run) >= length and run == char * len(run)


def _ends_finding(line: str, indent: int, after_blank: bool) -> bool:
    """Whether non-blank ``line`` ends a finding whose bullet is at ``indent``."""
    if HEADING_RE.match(line) or BREAK_RE.match(line):
        return True
    item = LIST_ITEM_RE.match(line)
    if item is not None and _width(item["indent"]) <= indent:
        return True  # a sibling list item that isn't a finding
    # after a blank line, text back at the bullet's column has left the list
    # item (a closing summary, say) -- unless it is an unindented Issue/Fix
    return after_blank and _indent_of(line) <= indent and not FIELD_RE.match(line)


def parse_findings(report: str) -> list[Finding]:
    """Split a report into findings in the shape of docs/finding-output.md.

    A finding starts at a ``- **[severity]`` bullet (``*``, ``1.`` and ``1)``
    markers also count) and, like a markdown list item, runs until the next
    finding, a heading, a thematic break, a sibling list item, or -- after a
    blank line -- text no longer indented past the bullet (unindented
    ``**Issue:**``/``**Fix:**`` lines are tolerated). Fenced code inside a
    finding is opaque: a ``#`` comment in a suggested fix is not a heading. A
    fence opened outside any finding (the whole report wrapped in
    ```` ```markdown ````) is looked into, and its closing line ends the
    finding it lands in.
    """
    findings: list[Finding] = []
    lines: list[str] | None = None  # the open finding's lines
    severity = ""
    indent = 0  # the open finding's bullet column
    after_blank = False
    inner: tuple[str, int] | None = None  # a fence opened inside the finding
    outer: tuple[str, int] | None = None  # a fence opened outside any finding

    def close() -> None:
        nonlocal lines, inner
        if lines is not None:
            findings.append(Finding(severity, "\n".join(lines).rstrip()))
        lines, inner = None, None

    for line in report.splitlines():
        start = FINDING_START_RE.match(line)
        if lines is not None and inner is not None:
            # fenced code is opaque -- unless a finding bullet at this
            # finding's own column shows the fence was never closed
            if start is None or _width(start["indent"]) > indent:
                lines.append(line)
                if _closes_fence(line, inner):
                    inner = None
                continue
            close()
        if start is not None:
            close()
            lines = [line]
            severity = start["severity"].strip().lower()
            indent = _width(start["indent"])
            after_blank = False
            continue
        if lines is not None:
            if not line.strip():
                lines.append(line)
                after_blank = True
                continue
            if (
                outer is not None
                and _closes_fence(line, outer)
                and _indent_of(line) <= indent
            ):
                # the wrapper's closing fence (a fence of the fix's own code
                # sits indented inside the finding)
                close()
                outer = None
                continue
            if not _ends_finding(line, indent, after_blank):
                lines.append(line)
                after_blank = False
                inner = _opens_fence(line)
                continue
            close()
        # outside any finding only fences matter, so findings inside a fence
        # (the whole report wrapped in ```markdown) still parse
        if outer is None:
            outer = _opens_fence(line)
        elif _closes_fence(line, outer):
            outer = None
    close()
    return findings


def drifted_findings(report: str) -> list[str]:
    """Severity-led list items that aren't in the finding format."""
    return [
        line.strip()
        for line in report.splitlines()
        if DRIFTED_FINDING_RE.match(line) and not FINDING_START_RE.match(line)
    ]


@functools.cache
def _term_re(term: str) -> re.Pattern[str]:
    # whole-word, case-insensitive; a multi-word phrase tolerates whitespace
    # (including a line wrap) and inline markdown between its words, so "no
    # assert" matches "no `assert`". Lookarounds rather than \b so terms that
    # start or end with punctuation (".gitlab-ci.yml") still match.
    words = (re.escape(word) for word in term.split())
    return re.compile(r"(?<!\w)" + r"[\s`*]+".join(words) + r"(?!\w)", re.IGNORECASE)


def mentions(text: str, term: str) -> bool:
    """True if ``term`` appears in ``text`` as a whole word or phrase."""
    return _term_re(term).search(text) is not None


def severity_rank(severity: str) -> int | None:
    return SEVERITIES.index(severity) if severity in SEVERITIES else None


def _locates(plant: Plant, finding: Finding) -> bool:
    return any(mentions(finding.text, term) for term in plant.locations)


def _describes(plant: Plant, finding: Finding) -> bool:
    return any(mentions(finding.text, keyword) for keyword in plant.keywords)


def _severe_enough(plant: Plant, finding: Finding) -> bool:
    if plant.min_severity is None:
        return True
    rank = severity_rank(finding.severity)
    return rank is not None and rank >= SEVERITIES.index(plant.min_severity)


def satisfies(plant: Plant, finding: Finding) -> bool:
    return (
        _locates(plant, finding)
        and _describes(plant, finding)
        and _severe_enough(plant, finding)
    )


def match_plants(
    plants: Sequence[Plant], findings: Sequence[Finding]
) -> dict[int, int]:
    """Pair plants with distinct satisfying findings: plant index -> finding index.

    A maximum bipartite matching (augmenting paths), so one finding can never
    account for two plants, and a greedy early choice can't strand a plant
    that only one finding satisfies.
    """
    candidates = [
        [j for j, finding in enumerate(findings) if satisfies(plant, finding)]
        for plant in plants
    ]
    owner: dict[int, int] = {}  # finding index -> plant index

    def augment(i: int, seen: set[int]) -> bool:
        for j in candidates[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or augment(owner[j], seen):
                owner[j] = i
                return True
        return False

    for i in range(len(plants)):
        augment(i, set())
    return {i: j for j, i in owner.items()}


def _miss_reason(plant: Plant, findings: Sequence[Finding]) -> str:
    where = "the file"
    if plant.locators:
        where += f" (or one of {list(plant.locators)})"
    need = f"a finding naming {where} and one of {list(plant.keywords)}"
    located = [f for f in findings if _locates(plant, f) and _describes(plant, f)]
    if not located:
        return f"missed plant: {plant.file} (need {need})"
    if not any(_severe_enough(plant, f) for f in located):
        found = ", ".join(sorted({f"[{f.severity}]" for f in located}))
        return (
            f"missed plant: {plant.file} (reported as {found}, below "
            f"min-severity {plant.min_severity})"
        )
    return (
        f"missed plant: {plant.file} (its matching finding already accounts for "
        "another plant; each plant needs its own finding)"
    )


def score(fixture: Fixture, report: str) -> tuple[list[str], bool]:
    """Return (problems, passed) for one fixture's report (the agent's stdout)."""
    findings = parse_findings(report)
    problems: list[str] = []
    if not report.strip():
        problems.append("empty report: the agent wrote nothing to stdout")
    elif fixture.plants and not findings:
        problems.append(
            "no findings parsed — output format drift? "
            f"(expected {len(fixture.plants)} planted finding(s) as "
            "'- **[severity] ...' bullets)"
        )
    else:
        # a finding the parser can't see can't count toward max-findings
        # either, which would quietly pass a clean-diff fixture
        drifted = drifted_findings(report)
        if drifted:
            problems.append(
                f"{len(drifted)} finding(s) not in the '- **[severity] ...' "
                f"format — output format drift? (first: {drifted[0]!r})"
            )
        matched = match_plants(fixture.plants, findings)
        problems.extend(
            _miss_reason(plant, findings)
            for i, plant in enumerate(fixture.plants)
            if i not in matched
        )
    if len(findings) > fixture.max_findings:
        problems.append(
            f"too many findings: {len(findings)} > max {fixture.max_findings} "
            "(false-positive pressure)"
        )
    return problems, not problems


def agent_problems(run: AgentRun) -> list[str]:
    """Why a run can't be scored at all, or [] if the agent finished cleanly."""
    if run.returncode is None:
        return [f"agent timed out after {run.timeout}s"]
    if run.returncode != 0:
        return [f"agent exited with status {run.returncode}"]
    return []


def evaluate(fixture: Fixture, run: AgentRun) -> tuple[list[str], bool]:
    """Score a run; a timed-out or failed agent fails the fixture unscored."""
    problems = agent_problems(run)
    if problems:
        return problems, False
    return score(fixture, run.stdout)


# -- running -----------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=evals", "-c", "user.email=evals@localhost", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def installable_skill(fixture: Fixture, adapter: str = DEFAULT_ADAPTER) -> Skill:
    """The bundled skill ``fixture`` exercises, checked against ``adapter``."""
    for skill in discover_skills(known_agents=set(ADAPTERS)):
        if skill.name == fixture.skill:
            if not ADAPTERS[adapter].supports(skill):
                raise FixtureError(
                    f"{fixture.name}: skill {skill.name} does not support "
                    f"agent {adapter!r}"
                )
            return skill
    raise FixtureError(f"{fixture.name}: no bundled skill named {fixture.skill!r}")


def skill_path(fixture: Fixture, adapter: str = DEFAULT_ADAPTER) -> str:
    """Where ``adapter`` installs the fixture's skill, relative to the repo."""
    skill = installable_skill(fixture, adapter)
    return ADAPTERS[adapter].relative_path(skill).as_posix()


def build_prompt(fixture: Fixture, adapter: str = DEFAULT_ADAPTER) -> str:
    return DEFAULT_PROMPT.format(
        skill=fixture.skill, skill_path=skill_path(fixture, adapter)
    )


def prepare_repo(
    fixture: Fixture, workdir: Path, adapter: str = DEFAULT_ADAPTER
) -> Path:
    """Materialize the fixture as a git repo with a ``change`` branch."""
    skill = installable_skill(fixture, adapter)
    repo = workdir / fixture.name
    shutil.copytree(fixture.path / "base", repo)
    # installed before the base commit, so the skill file is neither part of
    # the diff under review nor an untracked change the skill's scope step
    # would pick up
    ADAPTERS[adapter].install(skill, Scope.PROJECT, project_root=repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "change")
    shutil.copytree(fixture.path / "change", repo, dirs_exist_ok=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change under review")
    return repo


def _text(output: str | bytes | None) -> str:
    # TimeoutExpired carries captured output as bytes even with text=True
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


def run_agent(agent_cmd: str, prompt: str, repo: Path, timeout: int) -> AgentRun:
    cmd = [part.replace("{prompt}", prompt) for part in shlex.split(agent_cmd)]
    try:
        result = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise SystemExit(
            f"error: agent command not found: {cmd[0]!r} — install it or pass "
            "--agent-cmd"
        ) from None
    except subprocess.TimeoutExpired as exc:
        return AgentRun(_text(exc.stdout), _text(exc.stderr), None, timeout)
    return AgentRun(result.stdout, result.stderr, result.returncode, timeout)


def select_fixtures(skill: str | None = None) -> list[Fixture]:
    """Every fixture, or those exercising ``skill`` (or named ``skill``)."""
    fixtures = [
        load_fixture(path) for path in sorted(FIXTURES.iterdir()) if path.is_dir()
    ]
    return [f for f in fixtures if skill is None or skill in (f.name, f.skill)]


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--skill",
        help="run only this skill's fixtures, or one fixture by directory name",
    )
    parser.add_argument(
        "--agent-cmd",
        default=DEFAULT_AGENT_CMD,
        help="agent command; {prompt} is substituted (default: %(default)r)",
    )
    parser.add_argument(
        "--adapter",
        default=DEFAULT_ADAPTER,
        choices=sorted(ADAPTERS),
        help="skilldeck adapter that installs the skill (default: %(default)s)",
    )
    parser.add_argument(
        "--repeat",
        type=_positive_int,
        default=1,
        metavar="N",
        help="run each fixture N times and report its pass rate",
    )
    parser.add_argument(
        "--timeout", type=int, default=600, help="per-run agent timeout (s)"
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep the temp repos for inspection"
    )
    args = parser.parse_args(argv)

    try:
        fixtures = select_fixtures(args.skill)
        # fail fast, before any paid run, on a skill the adapter can't install
        prompts = {f.name: build_prompt(f, args.adapter) for f in fixtures}
    except FixtureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not fixtures:
        print(f"error: no fixture for {args.skill!r}", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="skilldeck-evals-"))
    print(f"work dir: {workdir}\n")
    pass_counts: dict[str, int] = {}
    for fixture in fixtures:
        passes = 0
        for attempt in range(1, args.repeat + 1):
            run_dir = workdir if args.repeat == 1 else workdir / f"run-{attempt}"
            repo = prepare_repo(fixture, run_dir, args.adapter)
            run = run_agent(args.agent_cmd, prompts[fixture.name], repo, args.timeout)
            (repo / "report.txt").write_text(run.stdout, encoding="utf-8")
            (repo / "stderr.txt").write_text(run.stderr, encoding="utf-8")
            problems, passed = evaluate(fixture, run)
            label = fixture.name if args.repeat == 1 else f"{fixture.name} #{attempt}"
            findings = len(parse_findings(run.stdout))
            print(f"{'PASS' if passed else 'FAIL'}  {label}  ({findings} findings)")
            for problem in problems:
                print(f"      {problem}")
            if not passed and run.stderr.strip():
                print("      agent stderr:")
                print(textwrap.indent(run.stderr.rstrip(), " " * 8))
            passes += passed
        pass_counts[fixture.name] = passes

    runs = len(fixtures) * args.repeat
    failed = runs - sum(pass_counts.values())
    if args.repeat > 1:
        print("\npass rate per fixture:")
        for name, passes in pass_counts.items():
            print(f"  {passes}/{args.repeat} ({passes / args.repeat:4.0%})  {name}")
        print(f"\n{runs - failed}/{runs} runs passed")
    else:
        print(f"\n{runs - failed}/{runs} fixtures passed")
    if args.keep or failed:
        print(f"reports kept in {workdir}")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
