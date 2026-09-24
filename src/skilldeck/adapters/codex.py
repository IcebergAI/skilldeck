"""OpenAI Codex adapter.

Codex (0.95.0 and later) loads skills from ``.agents/skills/<name>/SKILL.md``
in each directory from the project root down to where it runs, and from
``~/.agents/skills/<name>/SKILL.md`` for the user. ``CODEX_HOME`` does not
move ``~/.agents``; the ``$CODEX_HOME/skills`` directory it does move is
labelled deprecated in the Codex source.
"""

from __future__ import annotations

from ..targets import UserDir
from .skill_md import SkillMdAdapter


class CodexAdapter(SkillMdAdapter):
    name = "codex"
    project_dir = ".agents/skills"
    global_dir = UserDir(".agents", "skills")
