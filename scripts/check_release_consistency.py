#!/usr/bin/env python3
"""Check that the package version, CHANGELOG, and release tag agree.

With no arguments, asserts that ``pyproject.toml``'s ``[project].version``
matches the newest dated section in ``CHANGELOG.md``. Pass ``--tag`` with the
pushed git ref (e.g. ``v0.3.0`` or ``refs/tags/v0.3.0``) to additionally assert
the tag matches the package version before publishing.

See ``docs/releasing.md``. Pure standard library so it runs anywhere.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def project_version() -> str:
    """Return ``version`` from the ``[project]`` table of pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    start = re.search(r"^\[project\]", text, re.MULTILINE)
    if not start:
        raise SystemExit("error: no [project] table in pyproject.toml")
    section = re.split(r"^\[", text[start.end() :], maxsplit=1, flags=re.MULTILINE)[0]
    match = re.search(r'^version\s*=\s*"([^"]+)"', section, re.MULTILINE)
    if not match:
        raise SystemExit("error: no version in the [project] table")
    return match.group(1)


def latest_changelog_version() -> str:
    """Return the highest dated ``## [x.y.z] - DATE`` version in the CHANGELOG.

    Keep a Changelog puts the newest section first, but comparing version
    numbers (not file order) keeps the check honest if a section is ever
    added in the wrong place.
    """
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(
        r"^##\s*\[(\d+\.\d+\.\d+)\]\s*-\s*\d{4}-\d{2}-\d{2}", text, re.MULTILINE
    )
    if not versions:
        raise SystemExit("error: no dated version section in CHANGELOG.md")
    return max(versions, key=lambda v: tuple(int(part) for part in v.split(".")))


def normalize_tag(ref: str) -> str:
    """Reduce a tag ref (``refs/tags/v0.3.0``) to a bare version (``0.3.0``)."""
    tag = ref.rsplit("/", 1)[-1]
    return tag[1:] if tag.startswith("v") else tag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", help="release ref/tag to check against the package version"
    )
    args = parser.parse_args()

    version = project_version()
    changelog = latest_changelog_version()

    errors = []
    if version != changelog:
        errors.append(
            f"pyproject version {version!r} != newest CHANGELOG version {changelog!r}"
        )
    if args.tag:
        tag_version = normalize_tag(args.tag)
        if tag_version != version:
            errors.append(
                f"tag {args.tag!r} (-> {tag_version!r}) != "
                f"pyproject version {version!r}"
            )

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        print(
            "\nSee docs/releasing.md: the pyproject version, the newest dated "
            "CHANGELOG\nsection, and the release tag must all match.",
            file=sys.stderr,
        )
        return 1

    target = "CHANGELOG and tag" if args.tag else "CHANGELOG"
    print(f"ok: version {version} matches {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
