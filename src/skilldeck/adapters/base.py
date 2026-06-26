"""Adapter interface.

An adapter translates one canonical :class:`~skilldeck.registry.Skill` into the
file format and on-disk location a particular agent expects. Adding support for a
new agent means writing one subclass -- skill content never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..registry import Skill
from ..targets import Scope, base_dir


class Adapter(ABC):
    #: agent identifier, matched against a skill's ``supported-agents``
    name: str = ""

    @abstractmethod
    def relative_path(self, skill: Skill) -> Path:
        """Install location for ``skill``, relative to the scope base dir."""

    @abstractmethod
    def render(self, skill: Skill) -> str:
        """Render the skill into this agent's expected file contents."""

    def supports(self, skill: Skill) -> bool:
        return self.name in skill.supported_agents

    def destination(
        self, skill: Skill, scope: Scope, project_root: Optional[Path] = None
    ) -> Path:
        return base_dir(scope, project_root) / self.relative_path(skill)

    def install(
        self, skill: Skill, scope: Scope, project_root: Optional[Path] = None
    ) -> Path:
        dest = self.destination(skill, scope, project_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.render(skill), encoding="utf-8")
        return dest

    def uninstall(
        self, skill: Skill, scope: Scope, project_root: Optional[Path] = None
    ) -> Optional[Path]:
        dest = self.destination(skill, scope, project_root)
        if dest.exists():
            dest.unlink()
            return dest
        return None
