"""Kiro adapter.

Kiro picks up steering documents from ``.kiro/steering/<name>.md`` (project) or
``~/.kiro/steering/<name>.md`` (global).
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from .base import Adapter


class KiroAdapter(Adapter):
    name = "kiro"

    def relative_path(self, skill: Skill) -> Path:
        return Path(".kiro/steering") / f"{skill.name}.md"

    def render(self, skill: Skill) -> str:
        return skill.body
