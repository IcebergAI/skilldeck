"""GitHub Copilot adapter.

Copilot (VS Code agent mode, Copilot CLI, the cloud agent and code review)
loads project skills from ``.github/skills/<name>/SKILL.md`` and personal
skills from ``~/.copilot/skills/<name>/SKILL.md``. ``COPILOT_HOME`` replaces
the whole ``~/.copilot`` directory for Copilot CLI; the VS Code local agent
reads ``~/.copilot/skills`` regardless. The older prompt-file format is the
``copilot-prompt`` adapter.
"""

from __future__ import annotations

from ..targets import UserDir
from .skill_md import SkillMdAdapter


class CopilotAdapter(SkillMdAdapter):
    name = "copilot"
    project_dir = ".github/skills"
    global_dir = UserDir(".copilot", "skills", env="COPILOT_HOME")
