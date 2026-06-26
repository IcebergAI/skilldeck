"""OpenAI Codex adapter.

Codex CLI surfaces custom prompts from ``.codex/prompts/<name>.md`` (project) or
``~/.codex/prompts/<name>.md`` (global). It has no frontmatter convention, so the
body is written as-is.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from .base import Adapter


class CodexAdapter(Adapter):
    name = "codex"

    def relative_path(self, skill: Skill) -> Path:
        return Path(".codex/prompts") / f"{skill.name}.md"

    def render(self, skill: Skill) -> str:
        return skill.body
