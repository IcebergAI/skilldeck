"""Shared base for agents that read Agent Skills.

Every supported agent now loads the same ``SKILL.md`` format (the Agent Skills
specification, https://agentskills.io/specification): a ``<name>/`` directory
holding ``SKILL.md``, whose YAML frontmatter carries the skill's ``name`` and
``description`` above the Markdown body. Only the directories differ, so a
native adapter just declares them; ``docs/adapters.md`` lists each agent's
locations and the vendor sources they were checked against.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from .base import Adapter, yaml_frontmatter


class SkillMdAdapter(Adapter):
    creates_skill_dir = True
    installed_glob = "*/SKILL.md"

    def entry(self, skill: Skill) -> Path:
        return Path(skill.name) / "SKILL.md"

    def render(self, skill: Skill) -> str:
        fields: dict[str, object] = {
            "name": skill.name,
            "description": skill.description,
        }
        return f"{yaml_frontmatter(fields)}\n{skill.body}"
