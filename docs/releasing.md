# Releasing

How versioning works in this repo and how to cut a release. A CI guard
(`scripts/check_release_consistency.py`) enforces the mechanical parts, so these
rules can't silently drift.

## Versioning

- **Project version** lives in `pyproject.toml` `[project].version` and is the
  single source of truth; `uv.lock` mirrors it (run `uv lock` after a bump).
- **SemVer**, and the project is **pre-1.0**: a breaking change bumps the
  **minor** (`0.2 → 0.3`); features and fixes bump the minor or patch at
  discretion. (Dropping Python 3.9 in 0.2.0 was breaking; the two new skills in
  0.3.0 were additive.)
- **Skill versions are independent.** Each skill carries its own `version` in
  `meta.yaml`; bump it whenever that skill's content changes, regardless of the
  project version.

## CHANGELOG

[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Accumulate every
notable change under `## [Unreleased]` as you go. A dated `## [x.y.z] - DATE`
section is created at **release-prep** time (see below).

The **git tag is the source of truth for "published."** A dated section that has
no corresponding tag is *prepared but not yet shipped* — that is the current
state of the repo (nothing is tagged or on PyPI yet).

## Cutting a release

1. Choose the new version per SemVer.
2. In `CHANGELOG.md`, move the `[Unreleased]` entries into a new
   `## [x.y.z] - YYYY-MM-DD` section and leave `[Unreleased]` empty.
3. Bump `version` in `pyproject.toml`, then `uv lock`.
4. Run the full check suite:
   `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
5. Open a `Release x.y.z` PR and merge it once CI is green.

At this point the version is **prepared**. To actually **publish**:

6. Push a tag matching the version: `git tag vX.Y.Z && git push origin vX.Y.Z`.
   This triggers `.github/workflows/release.yml`, which re-checks the tag against
   the version and publishes to PyPI via Trusted Publishing.

## The consistency guard

`scripts/check_release_consistency.py` (pure stdlib) asserts:

- `pyproject` version **==** the newest dated CHANGELOG version — run on every PR
  by the `lint` job, and also by `tests/test_release_consistency.py` under
  `pytest`.
- on a tag push, the tag (minus the `v`) **==** the `pyproject` version — run by
  the release workflow before it builds or publishes.

So a version/CHANGELOG mismatch fails CI, and a mis-tagged release fails before
anything reaches PyPI.
