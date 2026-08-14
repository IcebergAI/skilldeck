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
2. Run `python scripts/prepare_release.py x.y.z`. It bumps `pyproject.toml`,
   dates the `[Unreleased]` CHANGELOG section (leaving a fresh empty one
   above), runs `uv lock`, regenerates the Claude Code plugin tree (whose
   manifest pins the project version), and re-runs the consistency guard.
3. Run the full check suite:
   `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
4. Open a `Release x.y.z` PR and merge it once CI is green.

At this point the version is **prepared**. To actually **publish**:

5. Push a tag matching the version: `git tag vX.Y.Z && git push origin vX.Y.Z`.
   This is the explicit publication authorization. The release workflow then:

   - re-checks tag, package, and changelog agreement;
   - stamps the full tag ref and commit into both Python distributions;
   - proves wheel, source distribution, and committed Claude plugin have the
     same canonical skill manifest;
   - builds and validates an SPDX 2.3 SBOM from a clean runtime-only install;
   - writes and verifies an exact `SHA256SUMS` file;
   - creates GitHub SLSA provenance and SBOM attestations;
   - publishes only the wheel and source distribution to PyPI with Trusted
     Publishing and its PEP 740 attestation;
   - creates the GitHub release from the same build bundle; and
   - downloads the public release again, verifies both channels, and proves a
     one-byte modification is rejected.

   Build, attestation, PyPI, and GitHub release permissions are isolated in
   separate jobs. No publish job rebuilds an artifact.

Before the first tag, an owner must configure the repository's `pypi`
environment and the matching pending/trusted publisher on PyPI. This is an
external release gate, not a value committed to the repository. Do not create a
tag until that configuration has been read back and the release PR is frozen.

Consumer verification is documented in
[verifying-releases.md](verifying-releases.md).

## The consistency guard

`scripts/check_release_consistency.py` (pure stdlib) asserts:

- `pyproject` version **==** the newest dated CHANGELOG version — run on every PR
  by the `lint` job, and also by `tests/test_release_consistency.py` under
  `pytest`.
- on a tag push, the tag (minus the `v`) **==** the `pyproject` version — run by
  the release workflow before it builds or publishes.

So a version/CHANGELOG mismatch fails CI, and a mis-tagged release fails before
anything reaches PyPI.

## Generated trust files

- `src/skilldeck/_content_manifest.json` and
  `claude-plugin/.skilldeck/content-manifest.json` are generated together by
  `scripts/build_plugin.py`; never edit either by hand.
- `src/skilldeck/_build_metadata.json` is committed with unavailable source
  fields for development. `scripts/stamp_build_metadata.py` writes an exact
  `refs/tags/vX.Y.Z` plus full commit only inside the authorized tag workflow.
- `scripts/verify_distribution_identity.py` fails closed on archive traversal,
  links, duplicate members, malformed manifests, missing/orphaned skills, or
  any wheel/sdist/plugin digest mismatch.
- `scripts/write_checksums.py` accepts exactly one wheel, one source
  distribution, and one SPDX document. It streams verification and rejects
  symlinks, malformed lines, duplicates, extras, and missing artifacts.
