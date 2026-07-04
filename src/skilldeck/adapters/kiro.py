"""Kiro adapter.

Kiro picks up steering documents from ``.kiro/steering/<name>.md`` (project) or
``~/.kiro/steering/<name>.md`` (global). Steering files are included in every
interaction by default, which is wrong for on-demand review prompts, so the
rendered document carries ``inclusion: manual`` frontmatter — the user pulls it
in explicitly (e.g. ``#<name>`` in chat) instead of it steering every turn.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from .base import Adapter


class KiroAdapter(Adapter):
    name = "kiro"
    installed_glob = ".kiro/steering/*.md"

    def relative_path(self, skill: Skill) -> Path:
        return Path(".kiro/steering") / f"{skill.name}.md"

    def render(self, skill: Skill) -> str:
        # Static frontmatter — no skill fields are interpolated, so there is
        # no injection surface here.
        return f"---\ninclusion: manual\n---\n\n{skill.body}"
