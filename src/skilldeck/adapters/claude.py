"""Claude adapter.

Claude Code loads skills from ``.claude/skills/<name>/SKILL.md`` (project) or
``~/.claude/skills/<name>/SKILL.md`` (global), with YAML frontmatter carrying the
name and description.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from .base import Adapter, yaml_frontmatter


class ClaudeAdapter(Adapter):
    name = "claude"
    creates_skill_dir = True
    installed_glob = ".claude/skills/*/SKILL.md"

    def relative_path(self, skill: Skill) -> Path:
        return Path(".claude/skills") / skill.name / "SKILL.md"

    def render(self, skill: Skill) -> str:
        fields: dict[str, object] = {
            "name": skill.name,
            "description": skill.description,
        }
        return f"{yaml_frontmatter(fields)}\n{skill.body}"
