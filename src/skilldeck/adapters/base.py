"""Adapter interface.

An adapter translates one canonical :class:`~skilldeck.registry.Skill` into the
file format and on-disk location a particular agent expects. Adding support for a
new agent means writing one subclass -- skill content never changes.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path

import yaml

from ..registry import Skill, SkillError
from ..stamp import Stamp, parse, stamp
from ..targets import Scope, base_dir


def yaml_frontmatter(fields: dict[str, object]) -> str:
    """Serialize ``fields`` into a YAML frontmatter block.

    Serialized rather than interpolated, so a value containing newlines or YAML
    metacharacters is quoted and cannot inject extra frontmatter keys or corrupt
    the document.
    """
    text = yaml.safe_dump(
        fields, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    return f"---\n{text}---\n"


def write_atomic(dest: Path, text: str) -> None:
    """Replace ``dest`` with ``text`` via a sibling temp file and ``os.replace``.

    An interrupted install leaves either the old file or the new one, never a
    half-written skill. The temp file is created exclusively (never through an
    existing path) with the umask applied, as a plain write would; an existing
    file's permissions carry over, plus owner-read (a skill its agent can't
    read is no use); and the temp file is removed on any failure. Callers
    refuse a read-only ``dest`` first, as a plain write would fail on it.
    """
    tmp = dest.with_name(f".{dest.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o666)
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if dest.exists():
            os.chmod(tmp, stat.S_IMODE(dest.stat().st_mode) | stat.S_IRUSR)
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


#: why an UNMANAGED regular file is refused; installs made before stamping
#: existed (skilldeck 0.3.0 and earlier) are the common case after an upgrade
_UNSTAMPED = (
    "has no skilldeck stamp (hand-written, from another tool, or installed by "
    "skilldeck 0.3.0 or earlier)"
)


def _entry_mode(path: Path) -> int | None:
    """``path``'s own ``st_mode``, without following a symlink; None if absent."""
    try:
        return path.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise SkillError(f"cannot inspect {path}: {exc}") from exc


def _special_kind(mode: int) -> str:
    """Name what a non-regular, non-symlink entry is, for error messages."""
    return "a directory" if stat.S_ISDIR(mode) else "a special file"


class InstallState(Enum):
    """How an installed copy of a skill relates to the bundled one."""

    NOT_INSTALLED = "not installed"
    #: something skilldeck did not write is at the destination: a file with no
    #: stamp (written by hand, by something else, or by a skilldeck version that
    #: predates stamping), a non-UTF-8 file, a directory, or a symlink --
    #: skilldeck never creates symlinks, so it never follows one to a stamp
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

    #: scopes this adapter can install into; agents without a stable
    #: filesystem location for user-level config are project-only
    scopes: tuple[Scope, ...] = (Scope.PROJECT, Scope.GLOBAL)

    @abstractmethod
    def relative_path(self, skill: Skill) -> Path:
        """Install location for ``skill``, relative to the scope base dir."""

    @abstractmethod
    def render(self, skill: Skill) -> str:
        """Render the skill into this agent's expected file contents."""

    def supports(self, skill: Skill) -> bool:
        return self.name in skill.supported_agents

    def check_scope(self, scope: Scope) -> None:
        """Raise :class:`SkillError` if this agent cannot install at ``scope``."""
        if scope not in self.scopes:
            raise SkillError(
                f"{self.name} does not support --scope {scope.value}: it has no "
                "stable file location for that scope"
            )

    def destination(
        self, skill: Skill, scope: Scope, project_root: Path | None = None
    ) -> Path:
        self.check_scope(scope)
        return base_dir(scope, project_root) / self.relative_path(skill)

    def _stamped(self, skill: Skill) -> str:
        return stamp(self.render(skill), skill.name, skill.version)

    def inspect(
        self, skill: Skill, scope: Scope, project_root: Path | None = None
    ) -> tuple[InstallState, Stamp | None]:
        """Compare the installed copy of ``skill`` against the bundled one.

        Only the destination itself is examined without following links; its
        parent directories are resolved normally (see ``docs/adapters.md``).
        """
        dest = self.destination(skill, scope, project_root)
        mode = _entry_mode(dest)
        if mode is None:
            return InstallState.NOT_INSTALLED, None
        # skilldeck only ever writes regular UTF-8 files, so a symlink (even
        # one pointing at a stamped file), a directory or a FIFO is not ours.
        if not stat.S_ISREG(mode):
            return InstallState.UNMANAGED, None
        try:
            text = dest.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return InstallState.UNMANAGED, None
        except OSError as exc:
            raise SkillError(f"cannot read {dest}: {exc}") from exc
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
        mode = _entry_mode(dest)
        if mode is not None:
            # Never follow a symlink at the destination: writing through it
            # would clobber the link target instead of the intended skill file.
            if stat.S_ISLNK(mode):
                raise SkillError(f"refusing to install through symlink: {dest}")
            if not stat.S_ISREG(mode):
                raise SkillError(
                    f"cannot install {skill.name}: {dest} is "
                    f"{_special_kind(mode)}, which skilldeck never replaces"
                )
            # Replacing a file only needs its directory to be writable, but a
            # read-only skill file was made that way on purpose; refuse it as
            # a plain write would.
            if not os.access(dest, os.W_OK):
                raise SkillError(
                    f"{dest} is read-only; make it writable to let skilldeck replace it"
                )
        if not force:
            state, _ = self.inspect(skill, scope, project_root)
            if state is InstallState.UNMANAGED:
                raise SkillError(
                    f"{dest} {_UNSTAMPED}; re-run with --force to overwrite it"
                )
            if state is InstallState.MODIFIED:
                raise SkillError(
                    f"{dest} has local modifications; "
                    "re-run with --force to overwrite them"
                )
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(dest, self._stamped(skill))
        except OSError as exc:
            raise SkillError(f"cannot install {skill.name} to {dest}: {exc}") from exc
        return dest

    def installed_files(
        self, scope: Scope, project_root: Path | None = None
    ) -> list[Path]:
        """Every file under the scope base dir this adapter may have written."""
        return sorted(base_dir(scope, project_root).glob(self.installed_glob))

    def uninstall(
        self,
        skill: Skill,
        scope: Scope,
        project_root: Path | None = None,
        *,
        force: bool = False,
    ) -> Path | None:
        dest = self.destination(skill, scope, project_root)
        mode = _entry_mode(dest)
        if mode is None:
            return None
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            raise SkillError(
                f"cannot uninstall {skill.name}: {dest} is "
                f"{_special_kind(mode)}, which skilldeck never deletes"
            )
        # Deleting is as destructive as overwriting, so the same stamp checks
        # as install apply: only an unedited skilldeck install goes without
        # --force. A symlink is only ever unlinked; its target is left alone.
        # --force skips reading the file, so even one skilldeck can't read
        # can be removed.
        if not force:
            if stat.S_ISLNK(mode):
                raise SkillError(
                    f"{dest} is a symlink skilldeck did not create; re-run "
                    "with --force to remove the link (its target is kept)"
                )
            state, _ = self.inspect(skill, scope, project_root)
            if state is InstallState.NOT_INSTALLED:
                return None
            if state is InstallState.UNMANAGED:
                raise SkillError(
                    f"{dest} {_UNSTAMPED}; re-run with --force to delete it"
                )
            if state is InstallState.MODIFIED:
                raise SkillError(
                    f"{dest} has local modifications; "
                    "re-run with --force to delete them"
                )
        try:
            dest.unlink()
        except OSError as exc:
            raise SkillError(
                f"cannot uninstall {skill.name} from {dest}: {exc}"
            ) from exc
        # Remove the per-skill directory this adapter created (e.g. Claude's
        # ``.claude/skills/<name>/``) once empty. Adapters that write into a
        # shared directory (``.codex/prompts``, ``.kiro/steering``) never set
        # ``creates_skill_dir``, so those directories are never touched — even
        # for a skill that happens to be named after one of them. Best effort:
        # the skill file is already gone, so a directory that can't be removed
        # (a symlink, a permissions problem) is left in place.
        if self.creates_skill_dir:
            parent = dest.parent
            with contextlib.suppress(OSError):
                if not any(parent.iterdir()):
                    parent.rmdir()
        return dest
