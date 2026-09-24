"""Kiro adapter.

Kiro's default agent loads skills from ``.kiro/skills/<name>/SKILL.md``
(workspace) and ``~/.kiro/skills/<name>/SKILL.md`` (global). ``KIRO_HOME``
moves the whole ``~/.kiro`` directory for Kiro CLI; like Kiro, skilldeck
treats an empty ``KIRO_HOME`` as unset. The older steering-file format is the
``kiro-steering`` adapter.
"""

from __future__ import annotations

from ..targets import UserDir
from .skill_md import SkillMdAdapter


class KiroAdapter(SkillMdAdapter):
    name = "kiro"
    project_dir = ".kiro/skills"
    global_dir = UserDir(".kiro", "skills", env="KIRO_HOME")
