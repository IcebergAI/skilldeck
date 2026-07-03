"""Adapter interface.

An adapter translates one canonical :class:`~skilldeck.registry.Skill` into the
file format and on-disk location a particular agent expects. Adding support for a
new agent means writing one subclass -- skill content never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path

from ..registry import Skill, SkillError
from ..stamp import Stamp, parse, stamp
from ..targets import Scope, base_dir


class InstallState(Enum):
    """How an installed copy of a skill relates to the bundled one."""

    NOT_INSTALLED = "not installed"
    #: a file exists but carries no skilldeck stamp -- written by hand, by
    #: something else, or by a skilldeck version that predates stamping
    UNMANAGED = "unmanaged"
    #: stamped, but the content was edited after install
    MODIFIED = "modified"
    #: stamped and unedited, but not what installing the bundled skill writes now
    STALE = "stale"
    CURRENT = "up to date"


class Adapter(ABC):
    #: agent identifier, matched against a skill's ``supported-agents``
    name: str = ""

    #: True if ``relative_path`` places each skill in its own directory (e.g.
    #: Claude's ``.claude/skills/<name>/``); uninstall reclaims that directory
    #: once empty. Leave False for adapters that write into a shared directory.
    creates_skill_dir: bool = False

    #: glob (relative to the scope base dir) matching every file this adapter
    #: installs; lets ``status`` find orphans of skills no longer bundled
    installed_glob: str = ""

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

    def _stamped(self, skill: Skill) -> str:
        return stamp(self.render(skill), skill.name, skill.version)

    def inspect(
        self, skill: Skill, scope: Scope, project_root: Path | None = None
    ) -> tuple[InstallState, Stamp | None]:
        """Compare the installed copy of ``skill`` against the bundled one."""
        dest = self.destination(skill, scope, project_root)
        if not dest.exists():
            return InstallState.NOT_INSTALLED, None
        text = dest.read_text(encoding="utf-8")
        found = parse(text)
        if found is None:
            return InstallState.UNMANAGED, None
        if found.modified:
            return InstallState.MODIFIED, found
        if text != self._stamped(skill):
            return InstallState.STALE, found
        return InstallState.CURRENT, found

    def install(
        self,
        skill: Skill,
        scope: Scope,
        project_root: Path | None = None,
        *,
        force: bool = False,
    ) -> Path:
        dest = self.destination(skill, scope, project_root)
        # Never follow a symlink at the destination: writing through it would
        # clobber the link target instead of the intended skill file.
        if dest.is_symlink():
            raise SkillError(f"refusing to install through symlink: {dest}")
        if dest.exists() and not force:
            state, _ = self.inspect(skill, scope, project_root)
            if state is InstallState.UNMANAGED:
                raise SkillError(
                    f"{dest} exists but was not written by skilldeck; "
                    "re-run with --force to overwrite it"
                )
            if state is InstallState.MODIFIED:
                raise SkillError(
                    f"{dest} has local modifications; "
                    "re-run with --force to overwrite them"
                )
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(self._stamped(skill), encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"cannot install {skill.name} to {dest}: {exc}") from exc
        return dest

    def installed_files(
        self, scope: Scope, project_root: Path | None = None
    ) -> list[Path]:
        """Every file under the scope base dir this adapter may have written."""
        return sorted(base_dir(scope, project_root).glob(self.installed_glob))

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
