"""Claude adapter.

Claude Code loads skills from ``.claude/skills/<name>/SKILL.md`` (project) or
``~/.claude/skills/<name>/SKILL.md`` (global), with YAML frontmatter carrying the
name and description.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..registry import Skill
from .base import Adapter


class ClaudeAdapter(Adapter):
    name = "claude"

    def relative_path(self, skill: Skill) -> Path:
        return Path(".claude/skills") / skill.name / "SKILL.md"

    def render(self, skill: Skill) -> str:
        # Serialize the frontmatter rather than interpolating, so a name or
        # description containing newlines or YAML metacharacters is quoted and
        # cannot inject extra frontmatter keys or corrupt the document.
        fields = yaml.safe_dump(
            {"name": skill.name, "description": skill.description},
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
        return f"---\n{fields}---\n\n{skill.body}"
