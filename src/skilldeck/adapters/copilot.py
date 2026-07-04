"""GitHub Copilot adapter.

Copilot (VS Code) surfaces prompt files from ``.github/prompts/
<name>.prompt.md``; the user runs one on demand with ``/<name>`` in chat. The
frontmatter ``description`` labels it in the prompt picker.

User-level prompt files live inside the VS Code profile's user-data directory,
which has no stable path relative to the home directory, so this adapter is
project-scope only.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from ..targets import Scope
from .base import Adapter, yaml_frontmatter


class CopilotAdapter(Adapter):
    name = "copilot"
    installed_glob = ".github/prompts/*.prompt.md"
    scopes = (Scope.PROJECT,)

    def relative_path(self, skill: Skill) -> Path:
        return Path(".github/prompts") / f"{skill.name}.prompt.md"

    def render(self, skill: Skill) -> str:
        fields: dict[str, object] = {"description": skill.description}
        return f"{yaml_frontmatter(fields)}\n{skill.body}"
