"""Discovery and loading of canonical skills.

A skill lives in ``skills/<name>/`` and is made of two files:

* ``meta.yaml`` -- metadata (name, description, category, version, supported agents)
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


class SkillError(Exception):
    """Raised when a skill directory is malformed."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    category: str
    version: str
    supported_agents: tuple[str, ...]
    body: str
    path: Path


def load_skill(skill_dir: Path, known_agents: Collection[str] | None = None) -> Skill:
    """Load and validate a single skill directory.

    If ``known_agents`` is given, every entry in ``supported-agents`` must be a
    member of it, so a typo'd agent name fails loudly instead of silently never
    matching an adapter.
    """
    meta_path = skill_dir / "meta.yaml"
    body_path = skill_dir / "skill.md"

    if not meta_path.is_file():
        raise SkillError(f"{skill_dir}: missing meta.yaml")
    if not body_path.is_file():
        raise SkillError(f"{skill_dir}: missing skill.md")

    try:
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"{skill_dir}: meta.yaml is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillError(f"{skill_dir}: meta.yaml must be a YAML mapping")
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise SkillError(f"{skill_dir}: meta.yaml missing fields: {', '.join(missing)}")

    name = _require_str(skill_dir, meta, "name")
    if len(name) > MAX_NAME_LENGTH or not NAME_RE.fullmatch(name):
        raise SkillError(
            f"{skill_dir}: meta.yaml name {name!r} must be at most "
            f"{MAX_NAME_LENGTH} lowercase letters, digits and single hyphens, "
            "starting and ending with a letter or digit"
        )
    if name != skill_dir.name:
        raise SkillError(
            f"{skill_dir}: meta.yaml name '{name}' "
            f"does not match directory name '{skill_dir.name}'"
        )

    description = _require_str(skill_dir, meta, "description")
    if "\n" in description or "\r" in description:
        raise SkillError(f"{skill_dir}: meta.yaml description must be a single line")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise SkillError(
            f"{skill_dir}: meta.yaml description is {len(description)} characters; "
            f"the limit is {MAX_DESCRIPTION_LENGTH}"
        )

    category = _require_str(skill_dir, meta, "category")

    raw_version = meta["version"]
    if not isinstance(raw_version, str):
        # An unquoted ``version: 1.10`` is the float 1.1 by the time it gets
        # here; stringifying it would silently record the wrong version.
        raise SkillError(
            f"{skill_dir}: meta.yaml version must be a string, but YAML read it "
            f"as {type(raw_version).__name__} {raw_version!r}; quote it, "
            'e.g. version: "1.10.0"'
        )
    if not VERSION_RE.fullmatch(raw_version):
        raise SkillError(
            f"{skill_dir}: meta.yaml version {raw_version!r} must be "
            "MAJOR.MINOR.PATCH, e.g. 0.1.0"
        )

    agents = meta["supported-agents"]
    if not isinstance(agents, list) or not agents:
        raise SkillError(f"{skill_dir}: supported-agents must be a non-empty list")
    if not all(isinstance(agent, str) for agent in agents):
        raise SkillError(f"{skill_dir}: supported-agents entries must be strings")
    duplicates = sorted({agent for agent in agents if agents.count(agent) > 1})
    if duplicates:
        raise SkillError(
            f"{skill_dir}: supported-agents lists agent(s) more than once: "
            f"{', '.join(duplicates)}"
        )

    if known_agents is not None:
        unknown = [a for a in agents if a not in known_agents]
        if unknown:
            raise SkillError(
                f"{skill_dir}: supported-agents has unknown agent(s): "
                f"{', '.join(unknown)}"
            )

    return Skill(
        name=name,
        description=description,
        category=category,
        version=raw_version,
        supported_agents=tuple(agents),
        body=body_path.read_text(encoding="utf-8"),
        path=skill_dir,
    )


def _require_str(skill_dir: Path, meta: dict[Any, Any], field: str) -> str:
    """Return ``meta[field]`` if it is a non-blank string, else fail loudly."""
    value = meta[field]
    if not isinstance(value, str) or not value.strip():
        raise SkillError(f"{skill_dir}: meta.yaml {field} must be a non-empty string")
    return value


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
    return skills
