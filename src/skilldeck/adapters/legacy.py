"""Older, pre-Agent-Skills formats.

Before the agents read ``SKILL.md``, skilldeck wrote each skill as a single file
in a format the agent already had: a Copilot prompt file, a Cursor rule, a Kiro
steering document, a Codex custom prompt. Three of those formats still load in
current agents and remain available as opt-in adapters for anyone on an agent
version too old for skills. Codex custom prompts are gone from Codex, so that
format is kept only so ``skilldeck migrate`` can find and move old installs.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import Skill
from ..targets import UserDir
from .base import Adapter, yaml_frontmatter


class LegacyAdapter(Adapter):
    """One file per skill, ``<name><suffix>``, in a directory shared with the
    user's own files.

    A legacy adapter has its own ``--agent`` name but applies to every skill
    that supports its base ``agent``, so no skill has to list it in
    ``supported-agents``.
    """

    #: the native agent this is an older format of
    agent: str = ""
    #: appended to the skill name to make the file name
    suffix: str = ""

    def entry(self, skill: Skill) -> Path:
        return Path(f"{skill.name}{self.suffix}")

    def supports(self, skill: Skill) -> bool:
        return self.agent in skill.supported_agents


class CopilotPromptAdapter(LegacyAdapter):
    """VS Code prompt files: ``.github/prompts/<name>.prompt.md``, run with
    ``/<name>`` in chat.

    ``agent: agent`` makes the prompt run in agent mode, where it can use tools
    such as running ``git diff``; without it the prompt runs in whatever mode
    the chat is in, which may be Ask. User-level prompt files live in the VS
    Code profile's user-data directory, which has no stable path, so this is
    project-scope only.
    """

    name = "copilot-prompt"
    agent = "copilot"
    suffix = ".prompt.md"
    installed_glob = "*.prompt.md"
    project_dir = ".github/prompts"

    def render(self, skill: Skill) -> str:
        fields: dict[str, object] = {
            "description": skill.description,
            "agent": "agent",
        }
        return f"{yaml_frontmatter(fields)}\n{skill.body}"


class CursorRuleAdapter(LegacyAdapter):
    """Cursor project rules: ``.cursor/rules/<name>.mdc``.

    A rule with a ``description`` and ``alwaysApply: false`` (and no globs) is
    agent-requested: the agent pulls it in when the description matches the
    task. Cursor reads ``.mdc`` frontmatter one ``key: value`` line at a time
    rather than as YAML, so the description is written on a single line; a
    folded one would reach Cursor cut off at the first line break. Cursor is
    not known to load user-level rules from disk, so this is project-scope
    only.
    """

    name = "cursor-rule"
    agent = "cursor"
    suffix = ".mdc"
    installed_glob = "*.mdc"
    project_dir = ".cursor/rules"

    def render(self, skill: Skill) -> str:
        fields: dict[str, object] = {
            "description": skill.description,
            "alwaysApply": False,
        }
        return f"{yaml_frontmatter(fields, wrap=False)}\n{skill.body}"


class KiroSteeringAdapter(LegacyAdapter):
    """Kiro steering documents: ``.kiro/steering/<name>.md`` (project) or
    ``~/.kiro/steering/<name>.md`` (global, moved by ``KIRO_HOME``).

    Steering files are included in every interaction by default, which is wrong
    for on-demand review prompts, so the document carries ``inclusion: manual``
    frontmatter: the user pulls it in explicitly (``#<name>`` in the IDE,
    ``/context add`` in Kiro CLI).
    """

    name = "kiro-steering"
    agent = "kiro"
    suffix = ".md"
    installed_glob = "*.md"
    project_dir = ".kiro/steering"
    global_dir = UserDir(".kiro", "steering", env="KIRO_HOME")

    def render(self, skill: Skill) -> str:
        # Static frontmatter — no skill fields are interpolated, so there is
        # no injection surface here.
        return f"---\ninclusion: manual\n---\n\n{skill.body}"


class CodexPromptAdapter(LegacyAdapter):
    """Where skilldeck used to install Codex skills, as custom prompts:
    ``.codex/prompts/<name>.md`` and ``~/.codex/prompts/<name>.md``.

    Codex only ever read custom prompts from ``$CODEX_HOME/prompts``, never
    from a project, and removed them altogether in Codex 0.118.0. Not an
    install target: ``skilldeck migrate`` uses it to find old installs, which
    were written under the home directory whatever ``CODEX_HOME`` said.
    """

    name = "codex-prompt"
    agent = "codex"
    suffix = ".md"
    installed_glob = "*.md"
    project_dir = ".codex/prompts"
    global_dir = UserDir(".codex", "prompts")

    def render(self, skill: Skill) -> str:
        return skill.body
