"""Discovery and loading of canonical skills.

A skill lives in ``skills/<name>/`` and is made of two files:

* ``meta.yaml`` -- metadata (name, description, category, version, supported agents)
* ``skill.md``  -- the agent-neutral skill body / prompt

This module turns those into :class:`Skill` objects. Adapters consume them to
render agent-specific output; nothing here knows about a particular agent.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import yaml

# Bundled ``skills/`` directory, co-located with this module inside the package.
# Resolving relative to ``__file__`` works identically for an editable checkout
# and an installed wheel, since hatchling ships the skill files alongside the code.
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

REQUIRED_FIELDS = ("name", "description", "category", "version", "supported-agents")


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

    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise SkillError(f"{skill_dir}: meta.yaml missing fields: {', '.join(missing)}")

    if meta["name"] != skill_dir.name:
        raise SkillError(
            f"{skill_dir}: meta.yaml name '{meta['name']}' "
            f"does not match directory name '{skill_dir.name}'"
        )

    agents = meta["supported-agents"]
    if not isinstance(agents, list) or not agents:
        raise SkillError(f"{skill_dir}: supported-agents must be a non-empty list")

    if known_agents is not None:
        unknown = [a for a in agents if a not in known_agents]
        if unknown:
            raise SkillError(
                f"{skill_dir}: supported-agents has unknown agent(s): "
                f"{', '.join(unknown)}"
            )

    return Skill(
        name=meta["name"],
        description=meta["description"],
        category=meta["category"],
        version=str(meta["version"]),
        supported_agents=tuple(agents),
        body=body_path.read_text(encoding="utf-8"),
        path=skill_dir,
    )


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


def get_skill(name: str, skills_dir: Path | None = None) -> Skill:
    """Load a single skill by name."""
    for skill in discover_skills(skills_dir):
        if skill.name == name:
            return skill
    raise SkillError(f"unknown skill: {name}")
