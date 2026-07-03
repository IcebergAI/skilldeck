"""Adapter interface.

An adapter translates one canonical :class:`~skilldeck.registry.Skill` into the
file format and on-disk location a particular agent expects. Adding support for a
new agent means writing one subclass -- skill content never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..registry import Skill, SkillError
from ..targets import Scope, base_dir


class Adapter(ABC):
    #: agent identifier, matched against a skill's ``supported-agents``
    name: str = ""

    #: True if ``relative_path`` places each skill in its own directory (e.g.
    #: Claude's ``.claude/skills/<name>/``); uninstall reclaims that directory
    #: once empty. Leave False for adapters that write into a shared directory.
    creates_skill_dir: bool = False

    @abstractmethod
    def relative_path(self, skill: Skill) -> Path:
        """Install location for ``skill``, relative to the scope base dir."""

    @abstractmethod
    def render(self, skill: Skill) -> str:
        """Render the skill into this agent's expected file contents."""

    def supports(self, skill: Skill) -> bool:
        return self.name in skill.supported_agents

    def destination(
        self, skill: Skill, scope: Scope, project_root: Path | None = None
    ) -> Path:
        return base_dir(scope, project_root) / self.relative_path(skill)

    def install(
        self, skill: Skill, scope: Scope, project_root: Path | None = None
    ) -> Path:
        dest = self.destination(skill, scope, project_root)
        # Never follow a symlink at the destination: writing through it would
        # clobber the link target instead of the intended skill file.
        if dest.is_symlink():
            raise SkillError(f"refusing to install through symlink: {dest}")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(self.render(skill), encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"cannot install {skill.name} to {dest}: {exc}") from exc
        return dest

    def uninstall(
        self, skill: Skill, scope: Scope, project_root: Path | None = None
    ) -> Path | None:
        dest = self.destination(skill, scope, project_root)
        if not dest.exists():
            return None
        dest.unlink()
        # Remove the per-skill directory this adapter created (e.g. Claude's
        # ``.claude/skills/<name>/``) once empty. Adapters that write into a
        # shared directory (``.codex/prompts``, ``.kiro/steering``) never set
        # ``creates_skill_dir``, so those directories are never touched — even
        # for a skill that happens to be named after one of them.
        if self.creates_skill_dir:
            parent = dest.parent
            if not any(parent.iterdir()):
                parent.rmdir()
        return dest
