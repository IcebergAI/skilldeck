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

Every invocation writes a provider-neutral run record (``run-record.json``,
see ``evals/run-record.schema.json``) to its work dir: the skilldeck version
and commit, each skill's and fixture's digest, the harness, its command
template, version and model, and one entry per planned run -- passed, failed,
timed out, errored or not run. Raw reports and stderr stay in the work dir as
separate files the record points to. ``--replay`` re-runs a record's exact
configuration after checking that no skill or fixture changed since.

This calls a real agent and costs real money -- it is run manually (e.g.
before a release), not in CI. CI only validates fixture structure and the
scorer, via ``tests/test_eval_fixtures.py`` and ``tests/test_eval_scoring.py``.
Runs are sequential (concurrency 1), and more than ``--max-runs`` planned runs
(default 50) are refused before anything starts.

Usage:
    python evals/run_evals.py                       # all fixtures, claude CLI
    python evals/run_evals.py --skill logging       # one skill's fixtures
    python evals/run_evals.py --repeat 5 --skill logging   # pass rate
    python evals/run_evals.py --harness codex       # codex CLI + codex adapter
    python evals/run_evals.py --model sonnet        # pass a model to the harness
    python evals/run_evals.py --agent-cmd 'claude -p {prompt}'
    python evals/run_evals.py --adapter codex --agent-cmd 'codex exec {prompt}'
    python evals/run_evals.py --dry-run             # validate + plan, no agent
    python evals/run_evals.py --replay run-record.json   # same config again
    python evals/run_evals.py --keep                # keep temp repos to inspect
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import functools
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skilldeck import __version__  # noqa: E402
from skilldeck.adapters import ADAPTERS  # noqa: E402
from skilldeck.provenance import (  # noqa: E402
    canonical_json,
    canonical_skill_digest,
    normalise_text,
    sha256_text,
)
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
#: the default cap on planned runs (fixtures x repeats) per invocation
DEFAULT_MAX_RUNS = 50
DEFAULT_TIMEOUT = 600
#: seconds allowed for a harness's ``--version`` probe
VERSION_PROBE_TIMEOUT = 30
RECORD_NAME = "run-record.json"
RECORD_SCHEMA_VERSION = 1
RECORD_TYPE = "skilldeck-eval-run"
_FIXTURE_DOMAIN = b"skilldeck-eval-fixture-v1\0"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

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


class ConfigError(ValueError):
    """Options that can't make a valid run (harness, budget, replay record)."""


class AgentStartError(RuntimeError):
    """The agent command could not be started at all."""


@dataclass(frozen=True)
class HarnessPreset:
    """A known agent CLI: its non-interactive command and matching adapter."""

    adapter: str
    #: the command template; ``{prompt}`` is replaced by the review prompt
    command: str
    #: the same command with the harness's model option (``{model}``)
    model_command: str


#: built-in harnesses; ``--harness custom`` takes its command from --agent-cmd
HARNESSES = {
    # Claude Code's print mode: one non-interactive turn, the reply on stdout
    "claude": HarnessPreset(
        adapter="claude",
        command=DEFAULT_AGENT_CMD,
        model_command="claude --model {model} -p {prompt}",
    ),
    # Codex CLI's non-interactive mode: progress on stderr, the final message
    # on stdout; its default sandbox is read-only, which a review needs no
    # more than
    "codex": HarnessPreset(
        adapter="codex",
        command="codex exec {prompt}",
        model_command="codex exec --model {model} {prompt}",
    ),
}
DEFAULT_HARNESS = "claude"
CUSTOM_HARNESS = "custom"


@dataclass(frozen=True)
class Harness:
    """The resolved agent to run: which CLI, how, and with which adapter."""

    name: str
    #: the exact command template: ``{prompt}``, and ``{model}`` with a model
    command: str
    adapter: str
    #: the model passed through ``{model}``; None leaves the harness default
    model: str | None = None

    @property
    def version_command(self) -> list[str] | None:
        """How to ask a preset harness its version (None for a custom one)."""
        if self.name not in HARNESSES:
            return None
        return [shlex.split(self.command)[0], "--version"]


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


def remove_tree(path: Path) -> None:
    """Delete ``path`` recursively, including read-only files.

    Git writes its object files read-only, which Windows refuses to delete, so
    a plain ``rmtree`` would leave every review repo behind there. Best effort:
    anything still undeletable is left in place rather than failing a run.
    """

    def clear_readonly_and_retry(func: object, target: str, _exc: object) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)  # type: ignore[operator]

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=clear_readonly_and_retry)
        else:
            shutil.rmtree(path, onerror=clear_readonly_and_retry)
    except OSError:
        pass


def _text(output: str | bytes | None) -> str:
    # TimeoutExpired carries captured output as bytes even with text=True
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output or ""


def agent_argv(agent_cmd: str, prompt: str, model: str | None = None) -> list[str]:
    """The agent's command line with ``{prompt}`` and ``{model}`` substituted.

    One pass, so a prompt that happens to contain ``{model}`` (or a model
    name containing ``{prompt}``) is passed through as-is.
    """
    values = {"prompt": prompt} if model is None else {"prompt": prompt, "model": model}
    pattern = re.compile(r"\{(" + "|".join(values) + r")\}")
    return [
        pattern.sub(lambda match: values[match[1]], part)
        for part in shlex.split(agent_cmd)
    ]


def run_agent(
    agent_cmd: str,
    prompt: str,
    repo: Path,
    timeout: int,
    model: str | None = None,
) -> AgentRun:
    cmd = agent_argv(agent_cmd, prompt, model)
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
        raise AgentStartError(
            f"agent command not found: {cmd[0]!r} — install it or pass --agent-cmd"
        ) from None
    except subprocess.TimeoutExpired as exc:
        return AgentRun(_text(exc.stdout), _text(exc.stderr), None, timeout)
    except OSError as exc:  # found but not runnable, e.g. not executable
        raise AgentStartError(
            f"agent command {cmd[0]!r} could not start: {exc}"
        ) from None
    return AgentRun(result.stdout, result.stderr, result.returncode, timeout)


def select_fixtures(skill: str | None = None) -> list[Fixture]:
    """Every fixture, or those exercising ``skill`` (or named ``skill``)."""
    fixtures = [
        load_fixture(path) for path in sorted(FIXTURES.iterdir()) if path.is_dir()
    ]
    return [f for f in fixtures if skill is None or skill in (f.name, f.skill)]


# -- harnesses ---------------------------------------------------------------


def resolve_harness(
    name: str | None = None,
    agent_cmd: str | None = None,
    adapter: str | None = None,
    model: str | None = None,
) -> Harness:
    """Combine --harness, --agent-cmd, --adapter and --model into a Harness.

    Without ``name``, an ``agent_cmd`` makes a custom harness and no command
    the default (claude). A preset supplies its command -- the one that passes
    ``{model}`` when a model is given -- and its matching adapter;
    ``agent_cmd`` and ``adapter`` override them.
    """
    if name is None:
        name = CUSTOM_HARNESS if agent_cmd is not None else DEFAULT_HARNESS
    if name == CUSTOM_HARNESS:
        if agent_cmd is None:
            raise ConfigError("--harness custom needs --agent-cmd")
        command, default_adapter = agent_cmd, DEFAULT_ADAPTER
    elif name in HARNESSES:
        preset = HARNESSES[name]
        if agent_cmd is not None:
            command = agent_cmd
        else:
            command = preset.command if model is None else preset.model_command
        default_adapter = preset.adapter
    else:
        choices = [*sorted(HARNESSES), CUSTOM_HARNESS]
        raise ConfigError(f"unknown harness {name!r}; choose from {choices}")
    adapter = adapter or default_adapter
    if adapter not in ADAPTERS:
        raise ConfigError(
            f"unknown adapter {adapter!r}; choose from {sorted(ADAPTERS)}"
        )
    if model is not None and not model.strip():
        raise ConfigError("--model must not be empty")
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ConfigError(f"agent command {command!r}: {exc}") from None
    if not parts:
        raise ConfigError("the agent command is empty")
    if not any("{prompt}" in part for part in parts):
        raise ConfigError(f"agent command {command!r} has no {{prompt}} placeholder")
    has_model = any("{model}" in part for part in parts)
    if model is not None and not has_model:
        raise ConfigError(
            f"--model needs a {{model}} placeholder in the agent command {command!r}"
        )
    if model is None and has_model:
        raise ConfigError(
            f"agent command {command!r} has a {{model}} placeholder; pass --model"
        )
    return Harness(name=name, command=command, adapter=adapter, model=model)


def harness_version(command: Sequence[str] | None) -> str | None:
    """The first line a harness's ``--version`` prints; None if that fails."""
    if not command:
        return None
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_PROBE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if result.returncode == 0 and lines else None


# -- identities and digests --------------------------------------------------


class SkillIdentity(TypedDict):
    name: str
    version: str
    #: skilldeck.provenance.canonical_skill_digest of meta.yaml + skill.md
    canonical_sha256: str
    #: the file the adapter installs, i.e. exactly what the agent reads
    rendered_sha256: str


class FixtureIdentity(TypedDict):
    name: str
    digest: str
    skill: SkillIdentity


def fixture_digest(path: Path) -> str:
    """Hash every file under a fixture directory, by POSIX path and content.

    Domain-separated and length-framed like the canonical skill digest. UTF-8
    text is hashed with normalised newlines, so a CRLF checkout on Windows
    and an LF one agree; any other file is hashed as raw bytes.
    """
    digest = hashlib.sha256(_FIXTURE_DOMAIN)
    files = sorted(
        (file.relative_to(path).as_posix(), file)
        for file in path.rglob("*")
        if file.is_file()
    )
    for relative, file in files:
        data = file.read_bytes()
        with contextlib.suppress(UnicodeDecodeError):
            data = normalise_text(data.decode("utf-8")).encode("utf-8")
        name = relative.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return f"sha256:{digest.hexdigest()}"


def runner_digest() -> str:
    """The digest of this runner (the scorer and the prompt live here)."""
    return sha256_text(Path(__file__).read_text(encoding="utf-8"))


def _git_output(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_PROBE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def source_identity() -> dict[str, object]:
    """The skilldeck version and, in a git checkout, its commit and state."""
    commit: str | None = None
    dirty: bool | None = None
    toplevel = _git_output("rev-parse", "--show-toplevel")
    # only this checkout's own commit: a source tree unpacked inside some
    # other repository must not borrow that repository's HEAD
    if toplevel is not None and _same_path(Path(toplevel.strip()), ROOT):
        head = (_git_output("rev-parse", "HEAD") or "").strip()
        if _COMMIT_RE.fullmatch(head):
            commit = head
            status = _git_output("status", "--porcelain")
            dirty = None if status is None else bool(status.strip())
    return {
        "version": __version__,
        "git_commit": commit,
        "git_dirty": dirty,
        "runner_sha256": runner_digest(),
    }


# -- planning ----------------------------------------------------------------


@dataclass(frozen=True)
class PlannedFixture:
    """A validated fixture, with the identity its runs are recorded under."""

    fixture: Fixture
    prompt: str
    identity: FixtureIdentity


def fixture_layout_problems(fixture: Fixture) -> list[str]:
    """What stops ``fixture`` from building a review repo with its plants."""
    problems = [
        f"{fixture.name}: missing {part}/ directory"
        for part in ("base", "change")
        if not (fixture.path / part).is_dir()
    ]
    problems.extend(
        f"{fixture.name}: plant file {plant.file} is not in change/"
        for plant in fixture.plants
        if not (fixture.path / "change" / plant.file).is_file()
    )
    return problems


def plan_fixture(fixture: Fixture, adapter: str) -> PlannedFixture:
    """Validate ``fixture`` for ``adapter`` and pin down its identity."""
    problems = fixture_layout_problems(fixture)
    if problems:
        raise FixtureError("; ".join(problems))
    skill = installable_skill(fixture, adapter)
    meta_text = (skill.path / "meta.yaml").read_text(encoding="utf-8")
    return PlannedFixture(
        fixture=fixture,
        prompt=build_prompt(fixture, adapter),
        identity={
            "name": fixture.name,
            "digest": fixture_digest(fixture.path),
            "skill": {
                "name": skill.name,
                "version": skill.version,
                "canonical_sha256": canonical_skill_digest(meta_text, skill.body),
                "rendered_sha256": sha256_text(ADAPTERS[adapter].render(skill)),
            },
        },
    )


def plan_fixtures(
    fixtures: Sequence[Fixture], adapter: str
) -> tuple[list[PlannedFixture], list[str]]:
    """Plan every fixture; also return every problem found, not just the first."""
    planned: list[PlannedFixture] = []
    problems: list[str] = []
    for fixture in fixtures:
        try:
            planned.append(plan_fixture(fixture, adapter))
        except FixtureError as exc:
            problems.append(str(exc))
    return planned, problems


def print_plan(
    planned: Sequence[PlannedFixture], harness: Harness, repeat: int, max_runs: int
) -> None:
    runs = len(planned) * repeat
    print(
        f"plan: {len(planned)} fixture(s) x {repeat} repeat(s) = {runs} run(s), "
        f"sequential (concurrency 1), max {max_runs}"
    )
    model = harness.model or "harness default"
    print(f"harness: {harness.name} (adapter {harness.adapter}, model {model})")
    print(f"command: {harness.command}")
    width = max((len(p.fixture.name) for p in planned), default=0)
    for p in planned:
        skill = p.identity["skill"]
        print(
            f"  {p.fixture.name:<{width}}  {skill['name']} {skill['version']}  "
            f"fixture {p.identity['digest'][:19]}  x{repeat}"
        )


# -- replay ------------------------------------------------------------------


@dataclass(frozen=True)
class ReplaySpec:
    """The configuration and identities a run record pins down."""

    harness: Harness
    harness_version: str | None
    repeat: int
    timeout: int
    fixtures: tuple[FixtureIdentity, ...]
    runner_sha256: str | None
    #: sha256 of the record itself, stored in the new record's replay_of
    record_sha256: str


def _get(where: str, mapping: object, key: str) -> object:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"{where}: missing {key!r}")
    return mapping[key]


def _get_str(where: str, mapping: object, key: str) -> str:
    value = _get(where, mapping, key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: {key!r} must be a non-empty string")
    return value


def _get_optional_str(where: str, mapping: object, key: str) -> str | None:
    value = _get(where, mapping, key)
    if value is not None and not isinstance(value, str):
        raise ConfigError(f"{where}: {key!r} must be a string or null")
    return value


def _get_count(where: str, mapping: object, key: str) -> int:
    value = _get(where, mapping, key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{where}: {key!r} must be a positive integer")
    return value


def _get_digest(where: str, mapping: object, key: str) -> str:
    value = _get_str(where, mapping, key)
    if not _DIGEST_RE.fullmatch(value):
        raise ConfigError(f"{where}: {key!r} is not a sha256 digest")
    return value


def load_replay(path: Path) -> ReplaySpec:
    """Read the configuration and identities to replay from a run record."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read the run record: {exc}") from None
    where = str(path)
    if _get(where, data, "record_type") != RECORD_TYPE:
        raise ConfigError(f"{where}: not a skilldeck eval run record")
    version = _get(where, data, "schema_version")
    if version != RECORD_SCHEMA_VERSION:
        raise ConfigError(
            f"{where}: unsupported schema_version {version!r} "
            f"(this runner reads {RECORD_SCHEMA_VERSION})"
        )
    harness_data = _get(where, data, "harness")
    config = _get(where, data, "config")
    raw_fixtures = _get(where, data, "fixtures")
    if not isinstance(raw_fixtures, list) or not raw_fixtures:
        raise ConfigError(f"{where}: 'fixtures' must be a non-empty list")
    identities: list[FixtureIdentity] = []
    for i, entry in enumerate(raw_fixtures):
        at = f"{where}: fixtures[{i}]"
        skill = _get(at, entry, "skill")
        identities.append(
            {
                "name": _get_str(at, entry, "name"),
                "digest": _get_digest(at, entry, "digest"),
                "skill": {
                    "name": _get_str(f"{at}.skill", skill, "name"),
                    "version": _get_str(f"{at}.skill", skill, "version"),
                    "canonical_sha256": _get_digest(
                        f"{at}.skill", skill, "canonical_sha256"
                    ),
                    "rendered_sha256": _get_digest(
                        f"{at}.skill", skill, "rendered_sha256"
                    ),
                },
            }
        )
    names = [identity["name"] for identity in identities]
    if len(names) != len(set(names)):
        raise ConfigError(f"{where}: a fixture is listed twice")
    source = _get(where, data, "skilldeck")
    return ReplaySpec(
        harness=resolve_harness(
            _get_str(f"{where}: harness", harness_data, "name"),
            _get_str(f"{where}: harness", harness_data, "command"),
            _get_str(where, data, "adapter"),
            _get_optional_str(f"{where}: harness", harness_data, "model"),
        ),
        harness_version=_get_optional_str(f"{where}: harness", harness_data, "version"),
        repeat=_get_count(f"{where}: config", config, "repeat"),
        timeout=_get_count(f"{where}: config", config, "timeout_s"),
        fixtures=tuple(identities),
        runner_sha256=_get_optional_str(f"{where}: skilldeck", source, "runner_sha256"),
        record_sha256=sha256_text(text),
    )


def replay_fixtures(spec: ReplaySpec) -> list[Fixture]:
    """Load the fixtures a record names, by directory name, in record order."""
    available = {path.name: path for path in FIXTURES.iterdir() if path.is_dir()}
    fixtures = []
    for identity in spec.fixtures:
        path = available.get(identity["name"])
        if path is None:
            raise ConfigError(
                f"fixture {identity['name']!r} from the record no longer exists"
            )
        fixtures.append(load_fixture(path))
    return fixtures


def replay_problems(recorded: FixtureIdentity, planned: PlannedFixture) -> list[str]:
    """How ``planned`` differs from the identity a run record pinned."""
    current = planned.identity
    name = recorded["name"]

    def changed(what: str, before: str, after: str) -> str:
        return f"{name}: {what} changed since the record ({before} -> {after})"

    before, after = recorded["skill"], current["skill"]
    pairs = (
        ("fixture content", recorded["digest"], current["digest"]),
        ("skill", before["name"], after["name"]),
        ("skill version", before["version"], after["version"]),
        ("skill content", before["canonical_sha256"], after["canonical_sha256"]),
        ("installed skill file", before["rendered_sha256"], after["rendered_sha256"]),
    )
    return [changed(what, old, new) for what, old, new in pairs if old != new]


# -- running and recording ---------------------------------------------------


def _now() -> str:
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


@dataclass
class RunEntry:
    """One planned run in the record; what the run never reached stays null."""

    attempt: int
    #: passed | failed | agent_failed | timed_out | error | not_run
    status: str
    problems: list[str]
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    exit_code: int | None = None
    finding_count: int | None = None
    #: work-dir-relative POSIX paths of the raw report and stderr
    artifacts: dict[str, str] | None = None
    #: the raw report and stderr themselves, only with --include-reports
    raw: dict[str, str] | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_record(self) -> dict[str, object]:
        return {
            **dataclasses.asdict(self),
            "passed": self.passed,
            "timed_out": self.status == "timed_out",
            # no harness preset reports these yet; null means "not reported"
            "usage": None,
            "cost_usd": None,
        }


def run_status(run: AgentRun, passed: bool) -> str:
    if run.returncode is None:
        return "timed_out"
    if run.returncode != 0:
        return "agent_failed"
    return "passed" if passed else "failed"


def attempt_run(
    planned: PlannedFixture,
    harness: Harness,
    attempt: int,
    workdir: Path,
    timeout: int,
    include_reports: bool = False,
) -> tuple[RunEntry, AgentRun | None]:
    """Build a fresh repo, run the agent in it, score it, and store its output.

    Raises AgentStartError if the agent command can't be started at all.
    """
    fixture = planned.fixture
    try:
        repo = prepare_repo(
            fixture, workdir / "repos" / f"run-{attempt}", harness.adapter
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        problem = f"could not build the review repo: {exc}"
        return RunEntry(attempt, "error", [problem]), None
    started_at, clock = _now(), time.monotonic()
    run = run_agent(harness.command, planned.prompt, repo, timeout, harness.model)
    duration = round(time.monotonic() - clock, 3)
    finished_at = _now()

    # raw output lives beside the record, never in it (unless asked for)
    out = workdir / "artifacts" / f"run-{attempt}" / fixture.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.txt").write_text(run.stdout, encoding="utf-8")
    (out / "stderr.txt").write_text(run.stderr, encoding="utf-8")
    problems, passed = evaluate(fixture, run)
    entry = RunEntry(
        attempt=attempt,
        status=run_status(run, passed),
        problems=problems,
        started_at=started_at,
        finished_at=finished_at,
        duration_s=duration,
        exit_code=run.returncode,
        finding_count=len(parse_findings(run.stdout)),
        artifacts={
            name: (out / f"{name}.txt").relative_to(workdir).as_posix()
            for name in ("report", "stderr")
        },
        raw={"report": run.stdout, "stderr": run.stderr} if include_reports else None,
    )
    return entry, run


def build_record(
    *,
    source: dict[str, object],
    harness: Harness,
    version: str | None,
    planned: Sequence[PlannedFixture],
    entries: dict[str, list[RunEntry]],
    config: dict[str, object],
    started_at: str,
    stopped: bool,
) -> dict[str, object]:
    """The run record: provider-neutral, and free of raw agent output."""
    runs = [entry for p in planned for entry in entries[p.fixture.name]]
    not_run = sum(entry.status == "not_run" for entry in runs)
    passed = sum(entry.passed for entry in runs)
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "status": "incomplete" if stopped else "complete",
        "started_at": started_at,
        "finished_at": _now(),
        "skilldeck": source,
        "environment": {"python": platform.python_version(), "platform": sys.platform},
        "harness": {
            "name": harness.name,
            "command": harness.command,
            "model": harness.model,
            "version": version,
            "version_command": harness.version_command,
        },
        "adapter": harness.adapter,
        "config": config,
        "fixtures": [
            {
                **p.identity,
                "prompt": p.prompt,
                "plant_count": len(p.fixture.plants),
                "max_findings": p.fixture.max_findings,
                "runs": [entry.to_record() for entry in entries[p.fixture.name]],
            }
            for p in planned
        ],
        "summary": {
            "planned": len(runs),
            "attempted": len(runs) - not_run,
            "passed": passed,
            "failed": len(runs) - not_run - passed,
            "not_run": not_run,
        },
    }


def write_record(path: Path, record: dict[str, object]) -> None:
    # sorted keys, LF newlines: the same record is the same bytes everywhere
    path.write_text(canonical_json(record), encoding="utf-8", newline="\n")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--skill",
        help="run only this skill's fixtures, or one fixture by directory name",
    )
    parser.add_argument(
        "--harness",
        choices=[*sorted(HARNESSES), CUSTOM_HARNESS],
        help=f"agent CLI preset (default: {DEFAULT_HARNESS}, or {CUSTOM_HARNESS} "
        "with --agent-cmd); sets the command and the matching adapter",
    )
    parser.add_argument(
        "--agent-cmd",
        help="agent command; {prompt} (and {model}) are substituted "
        f"(default: the harness's, {DEFAULT_AGENT_CMD!r} for claude)",
    )
    parser.add_argument(
        "--adapter",
        choices=sorted(ADAPTERS),
        help="skilldeck adapter that installs the skill (default: the "
        f"harness's; {DEFAULT_ADAPTER} for a custom harness)",
    )
    parser.add_argument(
        "--model",
        help="model to request, passed through the command's {model}; recorded "
        "in the run record (default: the harness's own default, unrecorded)",
    )
    parser.add_argument(
        "--repeat",
        type=_positive_int,
        metavar="N",
        help="run each fixture N times and report its pass rate (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_int,
        metavar="S",
        help=f"per-run agent timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--max-runs",
        type=_positive_int,
        default=DEFAULT_MAX_RUNS,
        metavar="N",
        help="refuse to start if more runs than this are planned "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the fixtures and print the planned runs; invoke no agent",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        metavar="RECORD",
        help="re-run a run record's configuration, refusing if a skill or "
        "fixture changed since",
    )
    parser.add_argument(
        "--include-reports",
        action="store_true",
        help="also copy each run's raw stdout and stderr into the run record",
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep the temp repos for inspection"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    replay: ReplaySpec | None = None
    try:
        if args.replay is not None:
            fixed = {
                "--skill": args.skill,
                "--harness": args.harness,
                "--agent-cmd": args.agent_cmd,
                "--adapter": args.adapter,
                "--model": args.model,
                "--repeat": args.repeat,
                "--timeout": args.timeout,
            }
            clashes = [flag for flag, value in fixed.items() if value is not None]
            if clashes:
                raise ConfigError(
                    "--replay takes its configuration from the record; drop "
                    + ", ".join(clashes)
                )
            replay = load_replay(args.replay)
            harness, repeat, timeout = replay.harness, replay.repeat, replay.timeout
            fixtures = replay_fixtures(replay)
        else:
            harness = resolve_harness(
                args.harness, args.agent_cmd, args.adapter, args.model
            )
            repeat = args.repeat or 1
            timeout = args.timeout or DEFAULT_TIMEOUT
            fixtures = select_fixtures(args.skill)
            if not fixtures:
                raise ConfigError(f"no fixture for {args.skill!r}")
    except (ConfigError, FixtureError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # fail fast, before any paid run, on a broken fixture or a skill the
    # adapter can't install -- or, replaying, on anything that changed
    planned, problems = plan_fixtures(fixtures, harness.adapter)
    if replay is not None and not problems:
        for recorded, current in zip(replay.fixtures, planned, strict=True):
            problems.extend(replay_problems(recorded, current))
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2

    print_plan(planned, harness, repeat, args.max_runs)
    total = len(planned) * repeat
    if total > args.max_runs:
        print(
            f"error: {total} planned runs exceed --max-runs {args.max_runs}; "
            "narrow --skill, lower --repeat, or raise --max-runs",
            file=sys.stderr,
        )
        return 2
    if args.dry_run:
        print("\ndry run: fixtures are valid; no agent was invoked")
        return 0

    source = source_identity()
    version = harness_version(harness.version_command)
    if replay is not None:
        if version != replay.harness_version:
            print(
                f"note: harness version {version!r} differs from the record's "
                f"{replay.harness_version!r}"
            )
        if source["runner_sha256"] != replay.runner_sha256:
            print("note: the eval runner (scorer or prompt) changed since the record")

    workdir = Path(tempfile.mkdtemp(prefix="skilldeck-evals-"))
    print(f"work dir: {workdir}\n")
    started_at = _now()
    entries: dict[str, list[RunEntry]] = {}
    pass_counts: dict[str, int] = {}
    stop: str | None = None  # why the remaining runs were not attempted
    status = 0
    for p in planned:
        fixture = p.fixture
        entries[fixture.name] = []
        passes = 0
        for attempt in range(1, repeat + 1):
            if stop is not None:
                entry = RunEntry(attempt, "not_run", [f"not run: {stop}"])
                entries[fixture.name].append(entry)
                continue
            label = fixture.name if repeat == 1 else f"{fixture.name} #{attempt}"
            run: AgentRun | None = None
            try:
                entry, run = attempt_run(
                    p, harness, attempt, workdir, timeout, args.include_reports
                )
            except AgentStartError as exc:
                stop, status = str(exc), 2
                entry = RunEntry(attempt, "error", [stop])
            except KeyboardInterrupt:
                stop, status = "interrupted", 130
                entry = RunEntry(attempt, "error", [stop])
            entries[fixture.name].append(entry)
            count = entry.finding_count
            findings = "" if count is None else f"  ({count} findings)"
            print(f"{'PASS' if entry.passed else 'FAIL'}  {label}{findings}")
            for problem in entry.problems:
                print(f"      {problem}")
            if not entry.passed and run is not None and run.stderr.strip():
                print("      agent stderr:")
                print(textwrap.indent(run.stderr.rstrip(), " " * 8))
            passes += entry.passed
        pass_counts[fixture.name] = passes

    config: dict[str, object] = {
        "repeat": repeat,
        "timeout_s": timeout,
        "max_runs": args.max_runs,
        "jobs": 1,
        "include_reports": args.include_reports,
        "replay_of": None if replay is None else replay.record_sha256,
    }
    record = build_record(
        source=source,
        harness=harness,
        version=version,
        planned=planned,
        entries=entries,
        config=config,
        started_at=started_at,
        stopped=stop is not None,
    )
    record_path = workdir / RECORD_NAME
    write_record(record_path, record)

    runs = len(planned) * repeat
    failed = runs - sum(pass_counts.values())
    if repeat > 1:
        print("\npass rate per fixture:")
        for name, passes in pass_counts.items():
            print(f"  {passes}/{repeat} ({passes / repeat:4.0%})  {name}")
        print(f"\n{runs - failed}/{runs} runs passed")
    else:
        print(f"\n{runs - failed}/{runs} fixtures passed")
    if stop is not None:
        print(f"stopped early: {stop}", file=sys.stderr)
    print(f"run record: {record_path}")
    print(f"reports and stderr: {workdir / 'artifacts'}")
    if args.keep or failed:
        print(f"review repos kept in {workdir / 'repos'}")
    else:
        remove_tree(workdir / "repos")
    return status or (1 if failed else 0)


if __name__ == "__main__":
    raise SystemExit(main())
