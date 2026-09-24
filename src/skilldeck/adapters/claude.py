"""Claude adapter.

Claude Code loads skills from ``.claude/skills/<name>/SKILL.md`` (project) or
``~/.claude/skills/<name>/SKILL.md`` (global). ``CLAUDE_CONFIG_DIR`` moves the
whole ``~/.claude`` directory, and Claude Code then reads personal skills only
from ``$CLAUDE_CONFIG_DIR/skills``. An empty ``CLAUDE_CONFIG_DIR`` is not
treated as unset (Claude Code resolves it against its working directory), so a
global install refuses it rather than guess.
"""

from __future__ import annotations

from ..targets import UserDir
from .skill_md import SkillMdAdapter


class ClaudeAdapter(SkillMdAdapter):
    name = "claude"
    project_dir = ".claude/skills"
    global_dir = UserDir(
        ".claude", "skills", env="CLAUDE_CONFIG_DIR", empty_is_unset=False
    )
