"""Install scopes.

Scope is orthogonal to which agent: it only decides the *base* directory that an
adapter's agent-specific subpath is appended to. Project-local installs live under
the project root; global installs live under the user's home directory.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional


class Scope(str, Enum):
    PROJECT = "project"
    GLOBAL = "global"


def base_dir(scope: Scope, project_root: Optional[Path] = None) -> Path:
    """Return the directory that adapter relative paths are resolved against."""
    if scope == Scope.GLOBAL:
        return Path.home()
    return (project_root or Path.cwd()).resolve()
