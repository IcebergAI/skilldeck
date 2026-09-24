"""Cursor adapter.

Cursor loads skills from ``.cursor/skills/<name>/SKILL.md`` in the workspace
and from ``~/.cursor/skills/<name>/SKILL.md`` for the user. No environment
variable moves them. The older rule format is the ``cursor-rule`` adapter.
"""

from __future__ import annotations

from ..targets import UserDir
from .skill_md import SkillMdAdapter


class CursorAdapter(SkillMdAdapter):
    name = "cursor"
    project_dir = ".cursor/skills"
    global_dir = UserDir(".cursor", "skills")
