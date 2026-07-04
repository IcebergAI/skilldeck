#!/usr/bin/env python3
"""Prepare a release: stamp the new version everywhere it must agree.

``python scripts/prepare_release.py 0.4.0`` performs the mechanical steps of
``docs/releasing.md``:

1. bump ``[project].version`` in ``pyproject.toml``
2. convert ``## [Unreleased]`` in ``CHANGELOG.md`` into a dated
   ``## [x.y.z] - YYYY-MM-DD`` section, leaving a fresh empty ``[Unreleased]``
   above it (refuses to release an empty Unreleased section)
3. re-lock (``uv lock``) so the lockfile mirrors the version
4. regenerate the Claude Code plugin tree, whose manifest pins the version
5. re-run the release-consistency guard

It does not commit, push, or tag: review the diff, open a ``Release x.y.z``
PR, and tag ``vX.Y.Z`` after the merge (which publishes to PyPI).
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_plugin  # noqa: E402

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def set_pyproject_version(version: str, root: Path = ROOT) -> str:
    """Set ``[project].version``; return the previous version."""
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("error: no version in pyproject.toml")
    old = match.group(1)
    if old == version:
        raise SystemExit(f"error: pyproject.toml is already at {version}")
    path.write_text(
        text[: match.start(1)] + version + text[match.end(1) :], encoding="utf-8"
    )
    return old


def cut_changelog(version: str, today: str, root: Path = ROOT) -> None:
    """Turn ``[Unreleased]`` into a dated section with a fresh one above it."""
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    header = "## [Unreleased]"
    if header not in text:
        raise SystemExit("error: CHANGELOG.md has no [Unreleased] section")
    after = text.split(header, 1)[1]
    pending = after.split("\n## [", 1)[0]
    if not pending.strip():
        raise SystemExit("error: [Unreleased] is empty — nothing to release")
    if f"## [{version}]" in text:
        raise SystemExit(f"error: CHANGELOG.md already has a {version} section")
    dated = f"{header}\n\n## [{version}] - {today}"
    path.write_text(text.replace(header, dated, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="the release version, e.g. 0.4.0")
    args = parser.parse_args()
    version = args.version.lstrip("v")
    if not VERSION_RE.match(version):
        raise SystemExit(f"error: {version!r} is not a MAJOR.MINOR.PATCH version")

    today = datetime.date.today().isoformat()
    cut_changelog(version, today)
    old = set_pyproject_version(version)
    print(f"version: {old} -> {version}; CHANGELOG section dated {today}")

    lock = subprocess.run(["uv", "lock"], cwd=ROOT)
    if lock.returncode != 0:
        print("warning: `uv lock` failed — run it manually", file=sys.stderr)

    build_plugin.write(build_plugin.generate())

    check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_release_consistency.py")]
    )
    if check.returncode != 0:
        return check.returncode

    print(
        "\nPrepared. Next:\n"
        "  1. uv run ruff check . && uv run ruff format --check . "
        "&& uv run mypy && uv run pytest\n"
        f"  2. open a 'Release {version}' PR and merge once CI is green\n"
        f"  3. git tag v{version} && git push origin v{version}  # publishes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
