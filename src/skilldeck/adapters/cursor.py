"""Cursor adapter.

Cursor loads project rules from ``.cursor/rules/<name>.mdc``, with MDC
frontmatter. A rule with a ``description`` and ``alwaysApply: false`` (and no
globs) is "agent-requested": the agent pulls it in when the description
matches the task, and the user can ``@``-mention it — the right behavior for
on-demand review prompts.

Cursor keeps user-level rules in app settings, not on the filesystem, so this
adapter is project-scope only.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from ..targets import Scope
from .base import Adapter, yaml_frontmatter


class CursorAdapter(Adapter):
    name = "cursor"
    installed_glob = ".cursor/rules/*.mdc"
    scopes = (Scope.PROJECT,)

    def relative_path(self, skill: Skill) -> Path:
        return Path(".cursor/rules") / f"{skill.name}.mdc"

    def render(self, skill: Skill) -> str:
        fields: dict[str, object] = {
            "description": skill.description,
            "alwaysApply": False,
        }
        return f"{yaml_frontmatter(fields)}\n{skill.body}"
