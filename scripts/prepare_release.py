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

Every check that can reject the release (version format, a version that is not
newer than the current one, an empty ``[Unreleased]``, an existing section for
the version) runs before any file is written. If ``uv lock`` fails, the
``pyproject.toml`` and ``CHANGELOG.md`` edits are rolled back and the script
exits non-zero, so a failed run never leaves a half-prepared tree.

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

import _pyproject  # noqa: E402
import build_plugin  # noqa: E402

VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
UNRELEASED = "## [Unreleased]"


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def bump_pyproject(text: str, version: str) -> tuple[str, str]:
    """Return ``text`` with ``[project].version`` set, and the previous version."""
    try:
        old = _pyproject.parse_project_version(text)
        start, end = _pyproject.version_span(text)
    except _pyproject.PyprojectError as exc:
        raise SystemExit(f"error: {exc}") from None
    if text[start:end] != old:
        raise SystemExit("error: cannot locate [project].version to rewrite it")
    if old == version:
        raise SystemExit(f"error: pyproject.toml is already at {version}")
    if VERSION_RE.fullmatch(old) and _key(version) < _key(old):
        raise SystemExit(f"error: {version} is older than the current version {old}")
    return text[:start] + version + text[end:], old


def cut_changelog(text: str, version: str, today: str) -> str:
    """Turn ``[Unreleased]`` into a dated section with a fresh one above it."""
    if UNRELEASED not in text:
        raise SystemExit("error: CHANGELOG.md has no [Unreleased] section")
    after = text.split(UNRELEASED, 1)[1]
    pending = after.split("\n## [", 1)[0]
    if not pending.strip():
        raise SystemExit("error: [Unreleased] is empty — nothing to release")
    if f"## [{version}]" in text:
        raise SystemExit(f"error: CHANGELOG.md already has a {version} section")
    return text.replace(UNRELEASED, f"{UNRELEASED}\n\n## [{version}] - {today}", 1)


def plan(version: str, today: str, root: Path = ROOT) -> tuple[str, dict[Path, str]]:
    """Validate the release; return the old version and every file's new text.

    Writes nothing: any reason to refuse the release surfaces here, before
    :func:`main` touches the tree.
    """
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"error: {version!r} is not a MAJOR.MINOR.PATCH version")
    pyproject = root / "pyproject.toml"
    changelog = root / "CHANGELOG.md"
    new_pyproject, old = bump_pyproject(pyproject.read_text(encoding="utf-8"), version)
    new_changelog = cut_changelog(changelog.read_text(encoding="utf-8"), version, today)
    return old, {pyproject: new_pyproject, changelog: new_changelog}


def _write(files: dict[Path, str]) -> None:
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")


def relock(root: Path = ROOT) -> bool:
    """Run ``uv lock``; report whether it succeeded."""
    try:
        return subprocess.run(["uv", "lock"], cwd=root).returncode == 0
    except OSError as exc:
        print(f"error: cannot run `uv lock`: {exc}", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="the release version, e.g. 0.4.0")
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")
    today = datetime.date.today().isoformat()

    old, edits = plan(version, today, ROOT)
    originals = {path: path.read_text(encoding="utf-8") for path in edits}
    _write(edits)
    print(f"version: {old} -> {version}; CHANGELOG section dated {today}")

    if not relock(ROOT):
        _write(originals)
        print(
            "error: `uv lock` failed; pyproject.toml and CHANGELOG.md were "
            "restored. Fix the lock problem and re-run.",
            file=sys.stderr,
        )
        return 1

    build_plugin.write(build_plugin.generate())

    check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_release_consistency.py")]
    )
    if check.returncode != 0:
        return check.returncode

    print(
        "\nPrepared. Next:\n"
        "  1. uv run --extra dev ruff check . "
        "&& uv run --extra dev ruff format --check . "
        "&& uv run --extra dev mypy && uv run --extra dev pytest\n"
        f"  2. open a 'Release {version}' PR and merge once CI is green\n"
        f"  3. git tag v{version} && git push origin v{version}  # publishes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
