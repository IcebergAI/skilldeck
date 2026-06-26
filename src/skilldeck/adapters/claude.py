"""Claude adapter.

Claude Code loads skills from ``.claude/skills/<name>/SKILL.md`` (project) or
``~/.claude/skills/<name>/SKILL.md`` (global), with YAML frontmatter carrying the
name and description.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from .base import Adapter


class ClaudeAdapter(Adapter):
    name = "claude"

    def relative_path(self, skill: Skill) -> Path:
        return Path(".claude/skills") / skill.name / "SKILL.md"

    def render(self, skill: Skill) -> str:
        frontmatter = (
            "---\n"
            f"name: {skill.name}\n"
            f"description: {skill.description}\n"
            "---\n\n"
        )
        return frontmatter + skill.body
