#!/usr/bin/env python3
"""Check that the package version, CHANGELOG, and release tag agree.

With no arguments, asserts that ``pyproject.toml``'s ``[project].version``
matches the newest dated section in ``CHANGELOG.md``. Pass ``--tag`` with the
pushed git ref (exactly ``vX.Y.Z`` or ``refs/tags/vX.Y.Z``; anything else is
rejected) to additionally assert the tag matches the package version before
publishing.

It also guards the Claude plugin release record
(``claude-plugin/.skilldeck/release.json``), which maps a plugin version string
to the content released under it: when the record's ``v<version>`` tag exists,
the record must be the tagged copy. ``--base <ref>`` (a PR's target branch)
adds two checks against that ref: without a version bump the record must not
change, and a version bump (a release PR) must leave the plugin at exactly the
new version rather than a development snapshot.

See ``docs/releasing.md``. Pure standard library (plus ``git`` for the record
checks, skipped outside a git checkout) so it runs anywhere.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _pyproject  # noqa: E402

# A release version: three ASCII numbers without leading zeros. PEP 440
# normalizes ``0.04.0`` to ``0.4.0`` in the built metadata, so a zero-padded
# version could never match the tag, manifest, and ``__version__`` at once.
_NUMBER = r"(?:0|[1-9][0-9]*)"
RELEASE_VERSION_RE = re.compile(rf"{_NUMBER}\.{_NUMBER}\.{_NUMBER}")
# The only accepted release tag shapes: ``vX.Y.Z`` or its full ref.
_TAG_RE = re.compile(rf"(?:refs/tags/)?v({RELEASE_VERSION_RE.pattern})")
_DATED_SECTION_RE = re.compile(
    r"^##\s*\[(\d+\.\d+\.\d+)\]\s*-\s*\d{4}-\d{2}-\d{2}", re.MULTILINE
)
RELEASE_RECORD = "claude-plugin/.skilldeck/release.json"
PLUGIN_JSON = "claude-plugin/.claude-plugin/plugin.json"


def version_key(version: str) -> tuple[int, ...]:
    """Sort key comparing ``X.Y.Z`` numerically (so 0.10.0 > 0.3.0)."""
    return tuple(int(part) for part in version.split("."))


def newest_dated_version(changelog: str) -> str | None:
    """The highest ``## [x.y.z] - DATE`` version in ``changelog``, if any."""
    versions = _DATED_SECTION_RE.findall(changelog)
    return max(versions, key=version_key) if versions else None


def project_version() -> str:
    """Return ``version`` from the ``[project]`` table of pyproject.toml."""
    try:
        return _pyproject.project_version(ROOT)
    except _pyproject.PyprojectError as exc:
        raise SystemExit(f"error: {exc}") from None


def latest_changelog_version() -> str:
    """Return the highest dated ``## [x.y.z] - DATE`` version in the CHANGELOG.

    Keep a Changelog puts the newest section first, but comparing version
    numbers (not file order) keeps the check honest if a section is ever
    added in the wrong place.
    """
    newest = newest_dated_version((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    if newest is None:
        raise SystemExit("error: no dated version section in CHANGELOG.md")
    return newest


def normalize_tag(ref: str) -> str:
    """Reduce ``refs/tags/vX.Y.Z`` or ``vX.Y.Z`` to the bare version ``X.Y.Z``.

    Anything else (a bare version, a nested ref such as ``refs/tags/x/v0.3.0``,
    a branch, a pre-release suffix, a zero-padded number) raises
    ``ValueError`` rather than being guessed at: the release workflow must only
    ever publish an exact tag.
    """
    match = _TAG_RE.fullmatch(ref)
    if not match:
        raise ValueError(
            f"release tag {ref!r} is not of the form vX.Y.Z or refs/tags/vX.Y.Z"
        )
    return match.group(1)


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, check=False
    )


def _git_file(ref: str, path: str) -> bytes | None:
    """``path`` as committed at ``ref``, or ``None`` if it is not there."""
    if _git("cat-file", "-e", f"{ref}:{path}").returncode != 0:
        return None
    return _git("show", f"{ref}:{path}").stdout


def _json_object(payload: bytes, label: str) -> dict[str, object]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} is not a JSON object")
    return data


def _same_record(payload: bytes, record: dict[str, object]) -> bool:
    try:
        return _json_object(payload, RELEASE_RECORD) == record
    except ValueError:
        return False


def plugin_record_errors(version: str, base: str | None = None) -> list[str]:
    """Problems with the plugin release record; ``[]`` if it may stand.

    A released plugin version string must keep the content it was released
    with, or users who already hold that string never receive the change
    (Claude Code updates only when the string differs). So the record may only
    change together with a project version bump, and a tagged record never.
    """
    path = ROOT / RELEASE_RECORD
    try:
        record = _json_object(path.read_bytes(), RELEASE_RECORD)
    except (OSError, ValueError) as exc:
        return [f"cannot read {RELEASE_RECORD}: {exc}"]
    try:
        in_git = _git("rev-parse", "--git-dir").returncode == 0
    except OSError:
        in_git = False
    if not in_git:
        if base:
            return [f"--base {base} needs a git checkout"]
        return []  # e.g. an unpacked sdist: nothing to compare with

    errors = []
    tag = f"refs/tags/v{record.get('version')}"
    if _git("rev-parse", "-q", "--verify", f"{tag}^{{commit}}").returncode == 0:
        tagged = _git_file(tag, RELEASE_RECORD)
        if tagged is not None and not _same_record(tagged, record):
            errors.append(
                f"{RELEASE_RECORD} differs from the copy tagged {tag}: a released "
                "plugin version must keep its content. Restore it with "
                f"`git checkout {tag} -- {RELEASE_RECORD}` and re-run "
                "scripts/build_plugin.py"
            )
    if not base:
        return errors

    if _git("rev-parse", "-q", "--verify", f"{base}^{{commit}}").returncode != 0:
        return [*errors, f"base ref {base!r} not found (fetch it first)"]
    base_pyproject = _git_file(base, "pyproject.toml")
    if base_pyproject is None:
        return [*errors, f"{base} has no pyproject.toml"]
    try:
        base_version = _pyproject.parse_project_version(base_pyproject.decode("utf-8"))
    except (UnicodeDecodeError, _pyproject.PyprojectError) as exc:
        return [*errors, f"cannot read {base}'s version: {exc}"]
    if base_version == version:
        base_record = _git_file(base, RELEASE_RECORD)
        if base_record is not None and not _same_record(base_record, record):
            errors.append(
                f"{RELEASE_RECORD} changed without a project version bump: only "
                "scripts/prepare_release.py may re-record the plugin content. "
                f"Restore it with `git checkout {base} -- {RELEASE_RECORD}` and "
                "re-run scripts/build_plugin.py"
            )
        return errors
    try:
        plugin = _json_object((ROOT / PLUGIN_JSON).read_bytes(), PLUGIN_JSON)
    except (OSError, ValueError) as exc:
        return [*errors, f"cannot read {PLUGIN_JSON}: {exc}"]
    if plugin.get("version") != version:
        errors.append(
            f"this change bumps the version to {version}, but the plugin is "
            f"development snapshot {plugin.get('version')!r}: its content changed "
            "after scripts/prepare_release.py ran (for example by merging main). "
            f"Restore the record with `git checkout {base} -- {RELEASE_RECORD}`, "
            "re-run scripts/build_plugin.py, and commit"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", help="release ref/tag to check against the package version"
    )
    parser.add_argument(
        "--base",
        help="git ref this change will merge into (a PR's target branch): "
        "check the plugin release record changes only with a version bump",
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
        try:
            tag_version = normalize_tag(args.tag)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if tag_version != version:
                errors.append(
                    f"tag {args.tag!r} (-> {tag_version!r}) != "
                    f"pyproject version {version!r}"
                )
    errors += plugin_record_errors(version, args.base)

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        print(
            "\nSee docs/releasing.md: the pyproject version, the newest dated "
            "CHANGELOG\nsection, and the release tag must all match, and the "
            "plugin release record\nchanges only with a version bump.",
            file=sys.stderr,
        )
        return 1

    target = "CHANGELOG and tag" if args.tag else "CHANGELOG"
    if args.base:
        target += f"; plugin release record agrees with {args.base}"
    print(f"ok: version {version} matches {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
