#!/usr/bin/env python3
"""Read ``[project].version`` from ``pyproject.toml``: the one shared parser.

Every release script (and CI) needs the package version, and all of them must
agree on where it comes from: the ``version`` key of the ``[project]`` table,
never a same-named key in another table (``[tool.*]``, ``[project.urls]``).

Parses with :mod:`tomllib` on Python 3.11+. Python 3.10 has no TOML parser in
the standard library and these scripts stay dependency-free, so there a
``[project]``-scoped line scan stands in; it understands only the plain
``version = "x.y.z"`` form this project uses and fails loudly on anything else.
``prepare_release.py`` also uses the scan (:func:`version_span`) to rewrite the
value in place, since ``tomllib`` reports no source positions.

Run directly to print the version: ``python3 scripts/_pyproject.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10: no stdlib TOML parser; scan_project_version() stands in
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent

# A table header line, ``[name]`` or ``[[name]]``, optionally with a comment.
_HEADER_RE = re.compile(r"^(\[\[?)[ \t]*([^\[\]\n]+?)[ \t]*\]\]?[ \t]*(?:#.*)?$", re.M)
# A top-level ``version = "..."`` line (basic string, no escapes).
_VERSION_RE = re.compile(r'^version[ \t]*=[ \t]*"([^"\\\n]*)"[ \t]*(?:#.*)?$', re.M)


class PyprojectError(ValueError):
    """``pyproject.toml`` has no single, readable ``[project].version``."""


def version_span(text: str) -> tuple[int, int]:
    """Return the offsets of the ``[project].version`` value, quotes excluded."""
    headers = list(_HEADER_RE.finditer(text))
    tables = [
        (index, header)
        for index, header in enumerate(headers)
        if header.group(1) == "[" and header.group(2) == "project"
    ]
    if not tables:
        raise PyprojectError("pyproject.toml has no [project] table")
    if len(tables) > 1:
        raise PyprojectError("pyproject.toml has more than one [project] table")
    index, header = tables[0]
    end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
    matches = list(_VERSION_RE.finditer(text, header.end(), end))
    if not matches:
        raise PyprojectError('pyproject.toml has no [project] version = "..." line')
    if len(matches) > 1:
        raise PyprojectError("pyproject.toml sets [project] version more than once")
    return matches[0].span(1)


def scan_project_version(text: str) -> str:
    """Read ``[project].version`` without a TOML parser (the 3.10 fallback)."""
    start, end = version_span(text)
    if start == end:
        raise PyprojectError("pyproject.toml has an empty [project] version")
    return text[start:end]


def parse_project_version(text: str) -> str:
    """Return ``[project].version`` from the text of a ``pyproject.toml``."""
    if tomllib is None:
        return scan_project_version(text)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PyprojectError(f"pyproject.toml is not valid TOML: {exc}") from exc
    project = data.get("project")
    if not isinstance(project, dict):
        raise PyprojectError("pyproject.toml has no [project] table")
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise PyprojectError("pyproject.toml has no [project] version string")
    return version


def project_version(root: Path = ROOT) -> str:
    """Return ``[project].version`` from ``root/pyproject.toml``."""
    path = root / "pyproject.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PyprojectError(f"cannot read {path}: {exc}") from exc
    return parse_project_version(text)


def main() -> int:
    try:
        print(project_version())
    except PyprojectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
