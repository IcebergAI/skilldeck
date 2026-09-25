"""Skill authoring: ``skilldeck new`` scaffolds a skill, ``skilldeck validate``
checks one.

Both work on a *skills directory*: a folder of ``<name>/meta.yaml`` +
``<name>/skill.md`` skills. In a skilldeck checkout the default is the
checkout's ``src/skilldeck/skills``, and the repository-only checks apply
too: an eval fixture under ``evals/fixtures/``, the skill's row in
``docs/finding-output.md``, and freshness of the generated plugin tree and
content manifests. Anywhere else the directory must be given explicitly, so
an organization can author its own skills with the same checks; nothing here
writes into the installed package.

Every check is local: files are read, adapters render in memory, and no
network or agent is involved. The eval-fixture and generated-output checks
import the checkout's own ``evals/run_evals.py`` and
``scripts/build_plugin.py``, so they run only for the checkout this skilldeck
itself runs from (:func:`_trusted_checkout`); validate never executes code
from any other tree. Symlinks inside a skill are reported, never followed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import yaml

from . import registry
from .adapters import ADAPTERS, ALL_ADAPTERS
from .capabilities import CAPABILITY_SCHEMA
from .catalog import skill_entry
from .lint import (
    ERROR,
    INCOMPLETE,
    PLACEHOLDER,
    SEVERITY_RUBRIC,
    SKILL_FILES,
    Problem,
    bundle_problems,
    command_problems,
    command_programs,
    description_problems,
    finding_output_problems,
    placeholder_problems,
    reference_problems,
    structure_problems,
)
from .registry import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    NAME_RE,
    Skill,
    SkillError,
    SkillMeta,
    check_meta,
    discover_skills,
    is_junk,
    is_link,
    link_kind,
    load_skill,
    replacement_errors,
)

#: where a checkout keeps its canonical skills and its eval fixtures
SKILLS_SUBDIR = Path("src", "skilldeck", "skills")
FIXTURES_SUBDIR = Path("evals", "fixtures")
FINDING_OUTPUT_DOC = Path("docs", "finding-output.md")
_PROJECT_NAME_RE = re.compile(r'^name\s*=\s*"skilldeck"\s*$', re.M)
#: a new skill's first version
INITIAL_VERSION = "0.1.0"
#: bumped on a breaking change to ``skilldeck validate --json``
REPORT_SCHEMA_VERSION = 1


# -- where skills live ------------------------------------------------------------


@dataclass(frozen=True)
class Checkout:
    """A skilldeck source checkout, where the repository-only checks apply."""

    root: Path

    @property
    def skills_dir(self) -> Path:
        return self.root / SKILLS_SUBDIR

    @property
    def fixtures_dir(self) -> Path:
        return self.root / FIXTURES_SUBDIR


def is_checkout(root: Path) -> bool:
    """Whether ``root`` is the top of a skilldeck source checkout."""
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return (
        (root / SKILLS_SUBDIR).is_dir()
        and (root / "scripts" / "build_plugin.py").is_file()
        and bool(_PROJECT_NAME_RE.search(text))
    )


def find_checkout(start: Path) -> Checkout | None:
    """The skilldeck checkout ``start`` is in, if any."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if is_checkout(candidate):
            return Checkout(candidate)
    return None


def checkout_of(skills_dir: Path) -> Checkout | None:
    """The checkout whose canonical skills directory is ``skills_dir``, if any.

    Only that directory gets the repository checks: another directory inside
    a checkout (a scratch copy, an organization's skills) is checked on its
    own.
    """
    resolved = skills_dir.resolve()
    if len(resolved.parents) < len(SKILLS_SUBDIR.parts):
        return None
    root = resolved.parents[len(SKILLS_SUBDIR.parts) - 1]
    if root / SKILLS_SUBDIR == resolved and is_checkout(root):
        return Checkout(root)
    return None


def installed_package_dir() -> Path | None:
    """The installed skilldeck package directory, unless it is a checkout's
    ``src/skilldeck`` (an editable install), where authoring is expected."""
    bundled = Path(registry.DEFAULT_SKILLS_DIR)
    if checkout_of(bundled) is not None:
        return None
    return bundled.resolve().parent


def display_path(path: Path, base: Path | None = None) -> str:
    """``path`` as a POSIX path, relative to ``base`` (the working directory)
    when it is under it.

    Symlinks are not resolved, so a path shows the way it was given rather
    than where a link points.
    """
    base = Path(os.path.abspath(base or Path.cwd()))
    absolute = Path(os.path.abspath(base / path))
    try:
        return absolute.relative_to(base).as_posix()
    except ValueError:
        return absolute.as_posix()


def skill_dirs(skills_dir: Path) -> list[Path]:
    """The skill directories in ``skills_dir``, as discovery finds them, plus
    any link discovery would refuse (validate reports it)."""
    return sorted(
        child
        for child in skills_dir.iterdir()
        if not child.name.startswith(".")
        and not is_junk(child.name)
        and (is_link(child) or child.is_dir())
    )


# -- skilldeck new --------------------------------------------------------------


class _MetaDumper(yaml.SafeDumper):
    """Indents list items under their key, as the bundled meta.yaml files do."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def title_for(name: str) -> str:
    """A ``# Title`` for skill ``name`` whose words spell the name."""
    return " ".join(part.capitalize() for part in name.split("-"))


#: what a new skill declares: the read-only review baseline the bundled
#: review skills use, matching the skeleton's Scope steps (read the
#: repository; git fetch, git diff and git ls-files; the git remote), so it
#: renders without a ``## Declared capabilities`` notice
REVIEW_CAPABILITIES: dict[str, object] = {
    "schema": CAPABILITY_SCHEMA,
    "files": {"read": "repo", "write": "none"},
    "commands": ["git fetch", "git diff", "git ls-files"],
    "network": ["the git remote, via git fetch, to bring the base branch up to date"],
    "credentials": [],
    "tools": [],
    "artifacts": [],
}


def meta_text(name: str, description: str, category: str, agents: Sequence[str]) -> str:
    fields: dict[str, object] = {
        "name": name,
        "description": description,
        "category": category,
        "version": INITIAL_VERSION,
        "supported-agents": list(agents),
        "capabilities": REVIEW_CAPABILITIES,
    }
    return yaml.dump(
        fields,
        Dumper=_MetaDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=float("inf"),
    )


_P = PLACEHOLDER

#: the skill.md skeleton: the structure every review skill shares, and a
#: placeholder wherever domain content goes; it states no domain guidance
SKILL_TEMPLATE = f"""\
# {{title}}

Review the **pending changes on the current branch** for {_P}: the concern
this skill reviews, in a sentence or two. {_P}: name the skills it pairs
with and the areas it leaves to them.

{_P}: name the authoritative sources the checklist below is grounded in,
as Markdown links to the pages you fetched (OWASP, CIS, vendor documentation).

## Scope

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
2. Review only changed files and the code paths they touch, but read the
   whole function or file around each hunk, not just the diff.
3. {_P}: which files and changes are in this skill's area.

## What to look for

{_P}: the checklist, grouped by category under `###` headings, each item
grounded in one of the sources cited above.

## Output

Report each finding as a single list item:

- **[severity] classifier** — `file:line`
  **Issue:** what is wrong (and, for a security finding, how it could be
  exploited).
  **Fix:** the concrete change that resolves it.

{{rubric}}{_P}: at most a short list of severity anchors for this skill's
domain, consistent with the rubric, or delete this line. The classifier is
{_P}: the taxonomy tag findings are labelled with. Order findings by
severity, highest first, and keep one issue per finding. For example:

- **[{_P}: severity] {_P}: classifier** — `{_P}: file:line`
  **Issue:** {_P}: a realistic issue this skill finds.
  **Fix:** {_P}: its concrete fix.

Verify before reporting: re-check each candidate against the surrounding
code, and drop any you cannot back with a concrete scenario. Prefer the few
findings that matter; if more than ~10 survive, report the ones worth a
human's time and summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed origin/main...HEAD (3 files): 1 finding, worst medium.` If the
change touches nothing in this skill's area, say so and stop. If it
introduces no problems, say so explicitly rather than manufacturing findings.
"""

PLACEHOLDER_DESCRIPTION = f"{_P}: say in one sentence what this skill reviews."

FIXTURE_TEMPLATE = f"""\
# Golden-diff eval fixture for {{name}}; see evals/README.md#adding-a-fixture.
# {_P}: put the pre-change tree in base/ and the change under review, with
# the defect(s) the skill must find planted in it, in change/. List each
# planted defect under plants, with keywords that describe the defect rather
# than echo the code; set max-findings; add the fixture's SAMPLE_REPORTS
# entry in tests/test_eval_fixtures.py; and delete both README.md files.
skill: {{name}}
plants: []
max-findings: 0
"""
FIXTURE_BASE_README = (
    f"{_P}: replace this file with the pre-change files the review needs as context.\n"
)
FIXTURE_CHANGE_README = (
    f"{_P}: replace this file with the changed files, including the planted "
    "defect(s).\n"
)


def _one_line(what: str, value: str, limit: int | None = None) -> str:
    if not value.strip() or value.splitlines() != [value]:
        raise ValueError(f"{what} must be a single non-empty line")
    if limit is not None and len(value) > limit:
        raise ValueError(f"{what} is {len(value)} characters; the limit is {limit}")
    return value


def scaffold(
    name: str,
    *,
    category: str,
    agents: Sequence[str],
    skills_dir: Path,
    description: str | None = None,
    eval_fixture: bool = True,
) -> dict[Path, str]:
    """The files ``skilldeck new`` writes for skill ``name``, in order.

    ``meta.yaml`` and a ``skill.md`` skeleton in ``skills_dir/name``; in a
    checkout (when ``skills_dir`` is its canonical skills directory) and with
    ``eval_fixture``, also an eval fixture skeleton in
    ``evals/fixtures/name``. Raises ``ValueError`` for a bad argument, or when
    anything it would write already exists or lies in the installed package.
    """
    if len(name) > MAX_NAME_LENGTH or not NAME_RE.fullmatch(name):
        raise ValueError(
            f"invalid skill name {name!r}: use at most {MAX_NAME_LENGTH} "
            "lowercase letters, digits and single hyphens, starting and ending "
            "with a letter or digit"
        )
    _one_line("--category", category)
    if description is None:
        description = PLACEHOLDER_DESCRIPTION
    else:
        _one_line("--description", description, MAX_DESCRIPTION_LENGTH)
        if not description.endswith("."):
            raise ValueError(
                "--description should be one sentence ending with a period"
            )
    unknown = [agent for agent in agents if agent not in ADAPTERS]
    if not agents or unknown:
        raise ValueError(
            f"supported agents must be some of {', '.join(sorted(ADAPTERS))}"
        )

    package = installed_package_dir()
    target = skills_dir.resolve()
    if package is not None and (target == package or package in target.parents):
        raise ValueError(
            f"{display_path(skills_dir)} is inside the installed skilldeck "
            "package, which skilldeck never writes into; pass --dir with your "
            "own skills directory, or work in a skilldeck checkout"
        )

    skill_dir = skills_dir / name
    files = {
        skill_dir / "meta.yaml": meta_text(name, description, category, agents),
        skill_dir / "skill.md": SKILL_TEMPLATE.format(
            title=title_for(name), rubric=SEVERITY_RUBRIC
        ),
    }
    checkout = checkout_of(skills_dir)
    fixture_dir = None
    if checkout is not None and eval_fixture:
        fixture_dir = checkout.fixtures_dir / name
        files[fixture_dir / "expected.yaml"] = FIXTURE_TEMPLATE.format(name=name)
        files[fixture_dir / "base" / "README.md"] = FIXTURE_BASE_README
        files[fixture_dir / "change" / "README.md"] = FIXTURE_CHANGE_README

    if skill_dir.exists() or skill_dir.is_symlink():
        raise ValueError(
            f"{display_path(skill_dir)} already exists; skilldeck new never "
            "overwrites a skill"
        )
    if fixture_dir is not None and (fixture_dir.exists() or fixture_dir.is_symlink()):
        raise ValueError(
            f"{display_path(fixture_dir)} already exists; pass --no-eval-fixture "
            "to leave it as it is"
        )
    return files


def write_files(files: dict[Path, str]) -> None:
    """Create each file (never replacing one), UTF-8 with LF line endings."""
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


# -- skilldeck validate ---------------------------------------------------------


@dataclass(frozen=True)
class SkillStatus:
    name: str
    #: the skill directory, as :func:`display_path` shows it
    path: str
    #: whether it is in a checkout's skills directory (repository checks)
    checkout: bool
    #: ok, incomplete (authoring work remains, nothing wrong) or invalid
    status: str


@dataclass(frozen=True)
class Skipped:
    """Checks that could not apply, and why."""

    check: str
    reason: str


@dataclass
class Report:
    skills: list[SkillStatus] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "ok": self.ok,
            "skills": [
                {
                    "name": skill.name,
                    "path": skill.path,
                    "checkout": skill.checkout,
                    "status": skill.status,
                }
                for skill in self.skills
            ],
            "problems": [
                {
                    "skill": problem.skill,
                    "path": problem.path,
                    "line": problem.line,
                    "rule": problem.rule,
                    "level": problem.level,
                    "message": problem.message,
                    "remediation": problem.remediation,
                }
                for problem in self.problems
            ],
            "skipped": [
                {"check": skipped.check, "reason": skipped.reason}
                for skipped in self.skipped
            ],
        }


def _trusted_checkout(checkout: Checkout) -> bool:
    """Whether ``checkout`` is the source of the skilldeck running now.

    The eval-fixture and generated-output checks import the checkout's own
    ``evals/run_evals.py`` and ``scripts/build_plugin.py``. That is only
    safe for the code already running: any tree can look like a skilldeck
    checkout (a fork, a downloaded archive), and validating it must never run
    what it contains.
    """
    running = Path(__file__).resolve().parent
    return (checkout.root / "src" / "skilldeck").resolve() == running


_SCRIPTS: dict[Path, ModuleType] = {}


def _load_script(path: Path) -> ModuleType:
    """Import a trusted checkout's script (``evals/run_evals.py``,
    ``scripts/build_plugin.py``) by path, once per process.

    Call it only for a checkout :func:`_trusted_checkout` accepts. The
    scripts put the checkout's directories on ``sys.path`` to import their
    helpers; that is undone afterwards, since skilldeck itself is already
    imported.
    """
    path = path.resolve()
    if path in _SCRIPTS:
        return _SCRIPTS[path]
    # the test suite's conftest has already loaded run_evals under its stem
    existing = sys.modules.get(path.stem)
    existing_file = getattr(existing, "__file__", None)
    if existing is not None and existing_file and Path(existing_file).resolve() == path:
        _SCRIPTS[path] = existing
        return existing
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    name = f"_skilldeck_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    saved = sys.path[:]
    # dataclasses resolve their module through sys.modules while it executes
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    finally:
        sys.path[:] = saved
    _SCRIPTS[path] = module
    return module


def _status(problems: Iterable[Problem]) -> str:
    levels = {problem.level for problem in problems}
    if ERROR in levels:
        return "invalid"
    if INCOMPLETE in levels:
        return "incomplete"
    return "ok"


def _read_text(path: Path) -> str | None:
    """``path``'s text, or None if it is unreadable or not UTF-8."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


class _Checker:
    """Validates the skills of one run, loading each directory's siblings and
    each checkout's scripts only once."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self._siblings: dict[Path, list[Skill]] = {}

    def show(self, path: Path) -> str:
        return display_path(path, self.base)

    def siblings(self, skills_dir: Path) -> list[Skill]:
        """The skills in ``skills_dir`` that load, for replacement checks."""
        if skills_dir not in self._siblings:
            loaded = []
            for child in skill_dirs(skills_dir):
                if is_link(child):
                    continue
                try:
                    loaded.append(load_skill(child, set(ADAPTERS)))
                except SkillError:
                    continue
            self._siblings[skills_dir] = loaded
        return self._siblings[skills_dir]

    def skill(
        self, skill_dir: Path, checkout: Checkout | None, trusted: bool
    ) -> tuple[list[Problem], list[Skipped]]:
        name = skill_dir.name
        meta_path = skill_dir / "meta.yaml"
        body_path = skill_dir / "skill.md"
        problems: list[Problem] = []
        skipped: list[Skipped] = []

        # A link is reported and never followed: its target's path and
        # contents must not reach the report. The skill directory itself
        # being one stops everything; a link (or directory) in place of
        # meta.yaml or skill.md stops that file being read.
        if is_link(skill_dir):
            return [
                Problem(
                    self.show(skill_dir),
                    "skill.link",
                    f"the skill directory is a {link_kind(skill_dir)}",
                    None,
                    name,
                )
            ], [
                Skipped(
                    f"every other check of {name}",
                    "validate does not follow a linked skill directory",
                )
            ]
        bundle = bundle_problems(skill_dir, self.show) if skill_dir.is_dir() else []
        problems += bundle
        # meta.yaml or skill.md that is a link, directory or special file
        shown = {self.show(skill_dir / file): file for file in SKILL_FILES}
        blocked = {shown[p.path] for p in bundle if p.path in shown}

        meta: SkillMeta | None = None
        if "meta.yaml" not in blocked:
            try:
                meta = check_meta(skill_dir, set(ADAPTERS))
            except SkillError as exc:
                problems.append(
                    Problem(
                        self.show(exc.file or meta_path),
                        exc.rule or "meta.syntax",
                        exc.detail,
                        exc.line,
                        name,
                    )
                )
            meta_text = _read_text(meta_path)
            if meta_text is not None:
                problems += placeholder_problems(meta_text, self.show(meta_path), name)

        body: str | None = None
        if "skill.md" not in blocked:
            if not body_path.is_file():
                problems.append(
                    Problem(
                        self.show(body_path),
                        "body.missing",
                        "missing skill.md",
                        None,
                        name,
                    )
                )
            else:
                body = _read_text(body_path)
                if body is None:
                    problems.append(
                        Problem(
                            self.show(body_path),
                            "body.encoding",
                            "skill.md is not valid UTF-8",
                            None,
                            name,
                        )
                    )
        if body is not None:
            where = self.show(body_path)
            problems += structure_problems(name, body, where)
            problems += reference_problems(name, body, where)
            problems += placeholder_problems(body, where, name)
            if meta is not None:
                programs = command_programs(
                    [
                        meta.capabilities,
                        *(s.capabilities for s in self.siblings(skill_dir.parent)),
                    ]
                )
                problems += command_problems(
                    name,
                    body,
                    meta.capabilities,
                    programs,
                    where,
                    self.show(meta_path),
                )

        # the bundle and local-link rules are reported above, so the skill is
        # rendered whenever its two files load
        skill = meta.skill(body, skill_dir) if meta and body is not None else None
        if skill is None:
            skipped.append(
                Skipped(
                    f"rendering and catalog entry of {name}",
                    "meta.yaml and skill.md must load first",
                )
            )
        else:
            problems += description_problems(
                name, skill.description, self.show(meta_path)
            )
            problems += self._rendering(skill, meta_path)
            problems += [
                Problem(
                    self.show(meta_path),
                    exc.rule or "meta.deprecated-replacement",
                    exc.detail,
                    skill=name,
                )
                for exc in replacement_errors(
                    [
                        *(s for s in self.siblings(skill_dir.parent) if s.name != name),
                        skill,
                    ]
                )
                if exc.file == meta_path
            ]

        if checkout is not None:
            doc = checkout.root / FINDING_OUTPUT_DOC
            text = _read_text(doc) if doc.is_file() and not doc.is_symlink() else None
            if text is not None:
                problems += finding_output_problems(text, name, self.show(doc))
            if trusted:
                fixture_problems, fixture_skipped = self._fixtures(name, checkout)
                problems += fixture_problems
                skipped += fixture_skipped
        return problems, skipped

    def _rendering(self, skill: Skill, meta_path: Path) -> list[Problem]:
        """Render the skill for every adapter that takes it, then its catalog
        entry (which renders it again for the native agents)."""
        problems = []
        for adapter_name, adapter in sorted(ALL_ADAPTERS.items()):
            if not adapter.supports(skill):
                continue
            try:
                adapter.render(skill)
            except (SkillError, ValueError, yaml.YAMLError) as exc:
                problems.append(
                    Problem(
                        self.show(meta_path),
                        "render.failed",
                        f"the {adapter_name} adapter cannot render it: {exc}",
                        skill=skill.name,
                    )
                )
        if problems:
            return problems
        try:
            skill_entry(skill)
        except (SkillError, OSError, UnicodeDecodeError, ValueError) as exc:
            problems.append(
                Problem(
                    self.show(meta_path),
                    "catalog.entry",
                    f"cannot build its catalog entry: {exc}",
                    skill=skill.name,
                )
            )
        return problems

    def _fixtures(
        self, name: str, checkout: Checkout
    ) -> tuple[list[Problem], list[Skipped]]:
        """The eval fixtures that exercise skill ``name``: present, loadable,
        well formed, free of placeholders, and at least one planted.

        Uses the checkout's own fixture loader, so the checkout must be
        trusted (see :func:`_trusted_checkout`).
        """
        fixtures_dir = checkout.fixtures_dir
        names = {child.name for child in skill_dirs(checkout.skills_dir)} | {name}
        candidates = (
            [
                path
                for path in sorted(fixtures_dir.iterdir())
                if path.is_dir() and _fixture_owner(path.name, names) == name
            ]
            if fixtures_dir.is_dir()
            else []
        )
        problems: list[Problem] = []
        skipped: list[Skipped] = []
        runner_path = checkout.root / "evals" / "run_evals.py"
        try:
            runner: ModuleType | None = _load_script(runner_path)
        except Exception as exc:
            runner = None
            skipped.append(
                Skipped(
                    f"eval fixture structure of {name}",
                    f"cannot load {self.show(runner_path)}: {exc}",
                )
            )
        planted = present = broken = 0
        for path in candidates:
            expected = path / "expected.yaml"
            if runner is None:
                present += expected.is_file()
                continue
            try:
                fixture = runner.load_fixture(path)
            except runner.FixtureError as exc:
                broken += 1
                problems.append(
                    Problem(
                        self.show(expected),
                        "eval.fixture-invalid",
                        str(exc).removeprefix(f"{expected}: "),
                        skill=name,
                    )
                )
                continue
            if fixture.skill != name:
                if path.name == name:
                    broken += 1
                    problems.append(
                        Problem(
                            self.show(expected),
                            "eval.fixture-invalid",
                            f"skill is {fixture.skill!r}, but the directory is "
                            f"named for {name}; a fixture directory is named "
                            "for the skill it exercises",
                            skill=name,
                        )
                    )
                continue
            present += 1
            planted += bool(fixture.plants)
            for message in runner.fixture_layout_problems(fixture):
                broken += 1
                problems.append(
                    Problem(
                        self.show(path),
                        "eval.fixture-invalid",
                        str(message).removeprefix(f"{path.name}: "),
                        skill=name,
                    )
                )
            problems += [
                Problem(
                    self.show(expected), "eval.keyword-echo", str(message), None, name
                )
                for message in runner.echoed_keywords(fixture)
            ]
            tolerance = runner.clean_tolerance_problem(fixture)
            if tolerance:
                problems.append(
                    Problem(
                        self.show(expected),
                        "eval.clean-tolerance",
                        tolerance,
                        None,
                        name,
                    )
                )
            for file in sorted(path.rglob("*")):
                if file.is_symlink() or not file.is_file():
                    continue
                if "__pycache__" in file.parts:
                    continue
                text = _read_text(file)
                if text is not None:
                    problems += placeholder_problems(text, self.show(file), name)
        if broken:
            return problems, skipped
        where = self.show(fixtures_dir / name)
        if not present:
            problems.append(
                Problem(
                    where,
                    "eval.fixture-missing",
                    f"no eval fixture exercises {name}",
                    skill=name,
                    hint=f"add {where}/ with expected.yaml, base/ and change/ "
                    "planting a defect the skill must find, and its "
                    "SAMPLE_REPORTS entry in tests/test_eval_fixtures.py; see "
                    "evals/README.md#adding-a-fixture",
                )
            )
        elif runner is not None and not planted:
            problems.append(
                Problem(
                    where,
                    "eval.fixture-missing",
                    f"{name}'s eval fixtures plant no defect (only clean-diff "
                    "fixtures)",
                    skill=name,
                    hint=f"plant a defect in {where}/change/ (or in a "
                    f"{name}-<variant> fixture), list it under plants in "
                    "expected.yaml, and add its SAMPLE_REPORTS entry in "
                    "tests/test_eval_fixtures.py; see "
                    "evals/README.md#adding-a-fixture",
                )
            )
        return problems, skipped

    def generated(self, checkout: Checkout) -> tuple[list[Problem], list[Skipped]]:
        """``scripts/build_plugin.py --check``, in process; the checkout must
        be trusted (see :func:`_trusted_checkout`)."""
        try:
            discover_skills(checkout.skills_dir, known_agents=set(ADAPTERS))
        except SkillError:
            return [], [
                Skipped(
                    "generated-output check",
                    f"a skill in {self.show(checkout.skills_dir)} does not "
                    "load; fix it first",
                )
            ]
        script = checkout.root / "scripts" / "build_plugin.py"
        try:
            build = _load_script(script)
            stale = build.stale(
                build.generate(checkout.root, checkout.skills_dir), checkout.root
            )
        except (Exception, SystemExit) as exc:
            return [
                Problem(
                    self.show(script),
                    "generated.unchecked",
                    f"cannot generate the plugin tree to compare: {exc}",
                )
            ], []
        messages = {
            "missing": "generated file is missing",
            "outdated": "generated file is out of date",
            "unexpected": "file in the generated tree that no skill generates",
        }
        problems = []
        for entry in stale:
            kind, _, relative = str(entry).partition(": ")
            problems.append(
                Problem(
                    self.show(checkout.root / relative),
                    "generated.stale",
                    messages.get(kind, str(entry)),
                )
            )
        return problems, []


def _fixture_owner(directory: str, names: Iterable[str]) -> str | None:
    """The skill a fixture directory is named for: the longest skill name it
    equals or extends with ``-<variant>``."""
    owners = [
        name for name in names if directory == name or directory.startswith(f"{name}-")
    ]
    return max(owners, key=len, default=None)


def validate(skill_paths: Sequence[Path], base: Path | None = None) -> Report:
    """Check every skill directory in ``skill_paths``.

    A skill in a checkout's canonical skills directory also gets the
    repository checks, and each such checkout's generated output is checked
    once. The checks that run a checkout's own scripts (eval fixtures,
    generated output) apply only to the checkout this skilldeck runs from;
    for any other they are skipped, never run. Problems are sorted: by
    skill, then file, line and rule, with checkout-wide ones last. ``base``
    (default: the working directory) is what paths are shown relative to.
    """
    checker = _Checker(Path(os.path.abspath(base or Path.cwd())))
    report = Report()
    checkouts: dict[Path, Checkout] = {}
    outside: set[str] = set()
    seen: set[Path] = set()
    trusted: dict[Path, bool] = {}
    for path in skill_paths:
        # shown as given (a symlinked skills directory keeps its name);
        # compared resolved
        skill_dir = Path(os.path.abspath(path))
        if skill_dir.resolve() in seen:
            continue
        seen.add(skill_dir.resolve())
        checkout = checkout_of(skill_dir.parent)
        if checkout is None:
            outside.add(checker.show(skill_dir.parent))
        else:
            checkouts[checkout.root] = checkout
            if checkout.root not in trusted:
                trusted[checkout.root] = _trusted_checkout(checkout)
        problems, skipped = checker.skill(
            skill_dir, checkout, checkout is not None and trusted[checkout.root]
        )
        report.problems += problems
        report.skipped += skipped
        report.skills.append(
            SkillStatus(
                name=skill_dir.name,
                path=checker.show(skill_dir),
                checkout=checkout is not None,
                status=_status(problems),
            )
        )
    for skills_dir in sorted(outside):
        report.skipped.append(
            Skipped(
                "repository checks (eval fixtures, finding-output doc, generated "
                f"output) for {skills_dir}",
                "not the src/skilldeck/skills directory of a skilldeck checkout",
            )
        )
    running = Path(__file__).resolve().parent
    for root, checkout in sorted(checkouts.items()):
        if not trusted[root]:
            report.skipped.append(
                Skipped(
                    "eval fixture and generated-output checks for "
                    f"{checker.show(root)}",
                    "they run that checkout's own scripts, and this skilldeck "
                    f"runs from {checker.show(running)}, not from its "
                    "src/skilldeck; run `uv run --extra dev skilldeck validate` "
                    "inside that checkout",
                )
            )
            continue
        problems, skipped = checker.generated(checkout)
        report.problems += problems
        report.skipped += skipped
    report.skills.sort(key=lambda skill: (skill.name, skill.path))
    report.problems.sort(key=Problem.sort_key)
    report.skipped.sort(key=lambda skipped: (skipped.check, skipped.reason))
    return report


def format_report(report: Report) -> list[str]:
    """The human-readable report, one output line per entry."""
    lines = []
    for problem in report.problems:
        where = problem.path + (f":{problem.line}" if problem.line else "")
        lines.append(f"{where}: {problem.level} [{problem.rule}] {problem.message}")
        lines.append(f"    fix: {problem.remediation}")
    if report.problems:
        lines.append("")
    for skill in report.skills:
        own = [p for p in report.problems if p.skill == skill.name]
        errors = sum(p.level == ERROR for p in own)
        incomplete = len(own) - errors
        if skill.status == "ok":
            detail = ""
        elif skill.status == "incomplete":
            detail = f" (no errors in the skill; {incomplete} authoring item(s) remain)"
        else:
            detail = f" ({errors} error(s), {incomplete} incomplete)"
        lines.append(f"{skill.name}: {skill.status}{detail}")
    for skipped in report.skipped:
        lines.append(f"skipped {skipped.check}: {skipped.reason}")
    counts = {
        status: sum(skill.status == status for skill in report.skills)
        for status in ("ok", "incomplete", "invalid")
    }
    summary = (
        f"{len(report.skills)} skill(s): {counts['ok']} ok, "
        f"{counts['incomplete']} incomplete, {counts['invalid']} invalid"
    )
    shared = sum(problem.skill is None for problem in report.problems)
    if shared:
        summary += f"; {shared} generated-output problem(s)"
    lines.append(summary)
    return lines
