"""Discovery and loading of canonical skills.

A skill lives in ``skills/<name>/`` and is made of two files:

* ``meta.yaml`` -- metadata (name, description, category, version, supported
  agents, and an optional ``deprecated`` record)
* ``skill.md``  -- the agent-neutral skill body / prompt

This module turns those into :class:`Skill` objects. Adapters consume them to
render agent-specific output; nothing here knows about a particular agent.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Bundled ``skills/`` directory, co-located with this module inside the package.
# Resolving relative to ``__file__`` works identically for an editable checkout
# and an installed wheel, since hatchling ships the skill files alongside the code.
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

REQUIRED_FIELDS = ("name", "description", "category", "version", "supported-agents")
# Every key meta.yaml may carry; anything else (say, a misspelt ``depreciated``)
# is an error rather than silently ignored.
ALLOWED_FIELDS = (*REQUIRED_FIELDS, "deprecated")

# ``name`` and ``description`` limits follow the Agent Skills specification
# (https://agentskills.io/specification), the ``SKILL.md`` format the Claude
# adapter renders: 1-64 lowercase ASCII letters, digits and hyphens with no
# leading, trailing or doubled hyphen; a 1-1024 character description. Adapters
# also build file paths from ``name``, so the pattern doubles as a path-safety
# check.
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
# A SemVer 2.0.0 normal version (https://semver.org/, item 2): MAJOR.MINOR.PATCH
# non-negative integers without leading zeroes.
_VERSION_PART = r"(?:0|[1-9][0-9]*)"
VERSION_RE = re.compile(rf"{_VERSION_PART}\.{_VERSION_PART}\.{_VERSION_PART}")
# ``deprecated`` is optional; absent means the skill is not deprecated.
DEPRECATION_FIELDS = ("since", "reason", "replacement")


class SkillError(Exception):
    """Raised when a skill directory is malformed.

    For a malformed skill, ``rule`` names the metadata rule it breaks (e.g.
    ``meta.version``; ``skilldeck validate`` lists them), ``file`` is the file
    that breaks it, ``line`` the 1-based line when known, and ``detail`` a
    one-line message without the leading skill directory. Other errors leave
    ``rule``, ``file`` and ``line`` None.
    """

    def __init__(
        self,
        message: str,
        *,
        rule: str | None = None,
        file: Path | None = None,
        detail: str | None = None,
        line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.rule = rule
        self.file = file
        self.detail = message if detail is None else detail
        self.line = line


def _invalid(
    skill_dir: Path, rule: str, detail: str, file: str = "meta.yaml"
) -> SkillError:
    """A :class:`SkillError` for ``skill_dir`` breaking metadata ``rule``."""
    return SkillError(
        f"{skill_dir}: {detail}", rule=rule, file=skill_dir / file, detail=detail
    )


@dataclass(frozen=True)
class Deprecation:
    """Why a skill is deprecated, from which of its versions, and what replaces it."""

    since: str
    reason: str
    replacement: str | None = None


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    category: str
    version: str
    supported_agents: tuple[str, ...]
    body: str
    path: Path
    deprecated: Deprecation | None = None


def load_skill(skill_dir: Path, known_agents: Collection[str] | None = None) -> Skill:
    """Load and validate a single skill directory.

    If ``known_agents`` is given, every entry in ``supported-agents`` must be a
    member of it, so a typo'd agent name fails loudly instead of silently never
    matching an adapter.
    """
    meta_path = skill_dir / "meta.yaml"
    body_path = skill_dir / "skill.md"

    if not meta_path.is_file():
        raise _invalid(skill_dir, "meta.missing", "missing meta.yaml")
    if not body_path.is_file():
        raise _invalid(skill_dir, "body.missing", "missing skill.md", "skill.md")

    meta = _load_meta(skill_dir, known_agents)

    try:
        body = body_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid(
            skill_dir,
            "body.encoding",
            f"skill.md is not valid UTF-8: {exc}",
            "skill.md",
        ) from exc

    return Skill(
        name=meta.name,
        description=meta.description,
        category=meta.category,
        version=meta.version,
        supported_agents=meta.supported_agents,
        body=body,
        path=skill_dir,
        deprecated=meta.deprecated,
    )


def check_meta(skill_dir: Path, known_agents: Collection[str] | None = None) -> None:
    """Validate ``skill_dir/meta.yaml`` alone, as :func:`load_skill` does.

    For ``skilldeck validate``, when ``skill.md`` cannot be read. Raises
    :class:`SkillError` as :func:`load_skill` would.
    """
    if not (skill_dir / "meta.yaml").is_file():
        raise _invalid(skill_dir, "meta.missing", "missing meta.yaml")
    _load_meta(skill_dir, known_agents)


@dataclass(frozen=True)
class _Meta:
    name: str
    description: str
    category: str
    version: str
    supported_agents: tuple[str, ...]
    deprecated: Deprecation | None


def _load_meta(skill_dir: Path, known_agents: Collection[str] | None) -> _Meta:
    """Read and validate ``skill_dir/meta.yaml``, which exists."""
    meta_path = skill_dir / "meta.yaml"
    try:
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except UnicodeDecodeError as exc:
        raise _invalid(
            skill_dir, "meta.encoding", f"meta.yaml is not valid UTF-8: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise SkillError(
            f"{skill_dir}: meta.yaml is not valid YAML: {exc}",
            rule="meta.syntax",
            file=meta_path,
            detail=f"meta.yaml is not valid YAML: {_yaml_problem(exc)}",
            line=_yaml_line(exc),
        ) from exc
    if not isinstance(meta, dict):
        raise _invalid(skill_dir, "meta.syntax", "meta.yaml must be a YAML mapping")
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise _invalid(
            skill_dir,
            "meta.missing-field",
            f"meta.yaml missing fields: {', '.join(missing)}",
        )
    unknown = sorted(str(key) for key in meta if key not in ALLOWED_FIELDS)
    if unknown:
        raise _invalid(
            skill_dir,
            "meta.unknown-field",
            f"meta.yaml has unknown field(s): {', '.join(unknown)}; "
            f"the fields are {', '.join(ALLOWED_FIELDS)}",
        )

    name = _require_str(skill_dir, meta, "name")
    if len(name) > MAX_NAME_LENGTH or not NAME_RE.fullmatch(name):
        raise _invalid(
            skill_dir,
            "meta.name",
            f"meta.yaml name {name!r} must be at most "
            f"{MAX_NAME_LENGTH} lowercase letters, digits and single hyphens, "
            "starting and ending with a letter or digit",
        )
    if name != skill_dir.name:
        raise _invalid(
            skill_dir,
            "meta.name-mismatch",
            f"meta.yaml name '{name}' does not match directory name '{skill_dir.name}'",
        )

    description = _require_str(skill_dir, meta, "description")
    # Any line boundary ``str.splitlines`` knows, not just \n and \r: YAML
    # double-quoted escapes such as "\u2028" or "\x85" also break the one-line
    # ``skilldeck list`` output.
    if description.splitlines() != [description]:
        raise _invalid(
            skill_dir,
            "meta.description",
            "meta.yaml description must be a single line (a folded "
            "block needs >- rather than >, which keeps a final line break)",
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise _invalid(
            skill_dir,
            "meta.description",
            f"meta.yaml description is {len(description)} characters; "
            f"the limit is {MAX_DESCRIPTION_LENGTH}",
        )

    category = _require_str(skill_dir, meta, "category")

    raw_version = _require_version(skill_dir, meta["version"], "version")

    agents = meta["supported-agents"]
    if not isinstance(agents, list) or not agents:
        raise _invalid(
            skill_dir,
            "meta.supported-agents",
            "supported-agents must be a non-empty list",
        )
    if not all(isinstance(agent, str) for agent in agents):
        raise _invalid(
            skill_dir,
            "meta.supported-agents",
            "supported-agents entries must be strings",
        )
    duplicates = sorted({agent for agent in agents if agents.count(agent) > 1})
    if duplicates:
        raise _invalid(
            skill_dir,
            "meta.supported-agents",
            f"supported-agents lists agent(s) more than once: {', '.join(duplicates)}",
        )

    if known_agents is not None:
        unknown = [a for a in agents if a not in known_agents]
        if unknown:
            raise _invalid(
                skill_dir,
                "meta.unknown-agent",
                f"supported-agents has unknown agent(s): {', '.join(unknown)}",
            )

    deprecated = (
        _load_deprecation(skill_dir, meta["deprecated"], name, raw_version)
        if "deprecated" in meta
        else None
    )

    return _Meta(
        name=name,
        description=description,
        category=category,
        version=raw_version,
        supported_agents=tuple(agents),
        deprecated=deprecated,
    )


def _yaml_problem(exc: yaml.YAMLError) -> str:
    """What is wrong with the YAML, on one line and without the source
    excerpt PyYAML quotes (which can echo a file's contents)."""
    if isinstance(exc, yaml.MarkedYAMLError) and exc.problem:
        if exc.context:
            return f"{exc.problem} ({exc.context})"
        return exc.problem
    return " ".join(str(exc).split())


def _yaml_line(exc: yaml.YAMLError) -> int | None:
    """The 1-based line PyYAML found the problem on, if it knows."""
    mark = getattr(exc, "problem_mark", None)
    return mark.line + 1 if mark is not None else None


def _require_str(skill_dir: Path, meta: dict[Any, Any], field: str) -> str:
    """Return ``meta[field]`` if it is a non-blank string, else fail loudly."""
    value = meta[field]
    if not isinstance(value, str) or not value.strip():
        raise _invalid(
            skill_dir, f"meta.{field}", f"meta.yaml {field} must be a non-empty string"
        )
    return value


def _require_version(skill_dir: Path, value: object, field: str) -> str:
    """Return ``value`` if it is a MAJOR.MINOR.PATCH string, else fail loudly."""
    rule = "meta.version" if field == "version" else "meta.deprecated"
    if not isinstance(value, str):
        # An unquoted ``version: 1.10`` is the float 1.1 by the time it gets
        # here; stringifying it would silently record the wrong version.
        raise _invalid(
            skill_dir,
            rule,
            f"meta.yaml {field} must be a string, but YAML read it "
            f"as {type(value).__name__} {value!r}; quote it, "
            f'e.g. {field.rpartition(".")[2]}: "1.10.0"',
        )
    if not VERSION_RE.fullmatch(value):
        raise _invalid(
            skill_dir,
            rule,
            f"meta.yaml {field} {value!r} must be MAJOR.MINOR.PATCH, e.g. 0.1.0",
        )
    return value


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _load_deprecation(
    skill_dir: Path, raw: object, name: str, version: str
) -> Deprecation:
    """Validate the optional ``deprecated`` mapping of skill ``name``.

    ``since`` is the skill's own version that first carried the deprecation,
    so it can be no later than ``version``. ``replacement``, when given, names
    another skill; :func:`discover_skills` checks that it exists.
    """
    shape = (
        "deprecated must be a mapping with since and reason (and optionally "
        "replacement); leave it out for a skill that is not deprecated"
    )
    if not isinstance(raw, dict):
        raise _invalid(skill_dir, "meta.deprecated", f"meta.yaml {shape}")
    unknown = sorted(str(key) for key in raw if key not in DEPRECATION_FIELDS)
    if unknown:
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            f"meta.yaml deprecated has unknown field(s): {', '.join(unknown)}; {shape}",
        )
    missing = [field for field in ("since", "reason") if field not in raw]
    if missing:
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            f"meta.yaml deprecated missing fields: {', '.join(missing)}",
        )

    since = _require_version(skill_dir, raw["since"], "deprecated.since")
    if _version_key(since) > _version_key(version):
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            f"meta.yaml deprecated.since {since!r} is later than "
            f"the skill's version {version!r}; since is the skill version that "
            "first carried the deprecation",
        )

    reason = raw["reason"]
    if isinstance(reason, str):
        # A folded ``reason: >`` block keeps one final line break. Dropping
        # trailing line breaks accepts it without changing any other value:
        # the single-line check below rejects every value that has one.
        reason = reason.rstrip("\r\n")
    if not isinstance(reason, str) or not reason.strip():
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            "meta.yaml deprecated.reason must be a non-empty string",
        )
    if reason.splitlines() != [reason] or len(reason) > MAX_DESCRIPTION_LENGTH:
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            "meta.yaml deprecated.reason must be a single line of "
            f"at most {MAX_DESCRIPTION_LENGTH} characters",
        )

    replacement = raw.get("replacement")
    if replacement is not None:
        if not isinstance(replacement, str) or not NAME_RE.fullmatch(replacement):
            raise _invalid(
                skill_dir,
                "meta.deprecated",
                "meta.yaml deprecated.replacement must be a skill "
                f"name or null, not {replacement!r}",
            )
        if replacement == name:
            raise _invalid(
                skill_dir,
                "meta.deprecated",
                "meta.yaml deprecated.replacement names the skill itself",
            )
    return Deprecation(since=since, reason=reason, replacement=replacement)


def discover_skills(
    skills_dir: Path | None = None, known_agents: Collection[str] | None = None
) -> list[Skill]:
    """Load every skill under ``skills_dir`` (sorted by name)."""
    root = skills_dir or DEFAULT_SKILLS_DIR
    if not root.is_dir():
        raise SkillError(f"skills directory not found: {root}")

    skills = [
        load_skill(child, known_agents)
        for child in sorted(root.iterdir())
        if child.is_dir() and not child.name.startswith(".")
    ]
    errors = replacement_errors(skills)
    if errors:
        raise errors[0]
    return skills


def replacement_errors(skills: list[Skill]) -> list[SkillError]:
    """One error per deprecated skill in ``skills`` whose replacement is not a
    current skill in ``skills`` that supports every agent the deprecated one
    does.

    A replacement that is missing, deprecated itself, or missing one of those
    agents would send users to a skill they cannot install or should not
    adopt.
    """
    by_name = {skill.name: skill for skill in skills}
    errors: list[SkillError] = []
    for skill in skills:
        if skill.deprecated is None or skill.deprecated.replacement is None:
            continue
        replacement = by_name.get(skill.deprecated.replacement)
        if replacement is None:
            detail = (
                "meta.yaml deprecated.replacement "
                f"{skill.deprecated.replacement!r} is not a skill in the same "
                "directory"
            )
        elif replacement.deprecated is not None:
            detail = (
                "meta.yaml deprecated.replacement "
                f"{replacement.name!r} is itself deprecated; name the skill "
                "that replaces it instead"
            )
        else:
            lacking = [
                agent
                for agent in skill.supported_agents
                if agent not in replacement.supported_agents
            ]
            if not lacking:
                continue
            detail = (
                "meta.yaml deprecated.replacement "
                f"{replacement.name!r} does not support {', '.join(lacking)}, "
                f"which {skill.name} supports; its users there would have no "
                "replacement to install"
            )
        errors.append(_invalid(skill.path, "meta.deprecated-replacement", detail))
    return errors
