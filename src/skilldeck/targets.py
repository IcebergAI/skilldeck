"""Install scopes and the directories they resolve to.

Scope is orthogonal to which agent. At project scope every agent reads its files
from a directory under the project root, so an adapter names that directory
relative to the root. At global scope each agent has its own user-level config
directory -- ``~/.claude``, ``~/.copilot``, ... -- which some agents let the
user move with an environment variable; an adapter describes it with a
:class:`UserDir` instead of computing it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .registry import SkillError


class Scope(str, Enum):
    PROJECT = "project"
    GLOBAL = "global"


def project_base(project_root: Path | None = None) -> Path:
    """The directory project-scope paths are resolved against."""
    return (project_root or Path.cwd()).resolve()


@dataclass(frozen=True)
class UserDir:
    """``subdir`` inside an agent's user-level config home.

    The home is ``~/<default>``, unless the environment variable ``env`` names
    another directory, as ``CLAUDE_CONFIG_DIR`` does for ``~/.claude``.
    """

    #: the config home's default location, relative to the user's home directory
    default: str
    #: the directory inside the config home, e.g. ``skills``
    subdir: str
    #: environment variable that relocates the whole config home, if any
    env: str | None = None
    #: whether the agent treats a set-but-empty ``env`` as unset. When it
    #: doesn't (Claude Code resolves an empty ``CLAUDE_CONFIG_DIR`` against its
    #: working directory), there is no stable location to install to, so
    #: resolving refuses instead of guessing.
    empty_is_unset: bool = True

    def home(self) -> Path:
        """The config home: ``$env`` when set, else ``~/<default>``."""
        value = os.environ.get(self.env) if self.env else None
        if value is None or (value == "" and self.empty_is_unset):
            return Path.home() / self.default
        if value == "":
            raise SkillError(
                f"{self.env} is set but empty, which the agent does not treat "
                "as unset: it resolves its config directory against the "
                "directory it was started in. Unset it, or set it to an "
                "absolute path"
            )
        path = Path(value)
        # The agent resolves a relative path (or an unexpanded "~") against its
        # own working directory, which skilldeck can't know.
        if not path.is_absolute():
            raise SkillError(
                f"{self.env}={value!r} is not an absolute path, so where the "
                "agent looks depends on the directory it was started in; set "
                "it to an absolute path"
            )
        return path

    def resolve(self) -> Path:
        """The absolute directory this describes."""
        return self.home() / self.subdir
