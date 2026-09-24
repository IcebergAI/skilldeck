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
   It validates everything first (a plain `X.Y.Z` with no leading zeros,
   newer than both the current version and the newest dated CHANGELOG
   section, an `[Unreleased]` section with at least one entry, no existing
   section for the version) and writes nothing if any check fails; if
   `uv lock` or plugin generation fails it restores `pyproject.toml`,
   `CHANGELOG.md`, and `uv.lock` and exits non-zero.
3. Run the full check suite:
   `uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy && uv run --extra dev pytest`
4. Open a `Release x.y.z` PR and merge it once CI is green.

At this point the version is **prepared**. To actually **publish**:

5. Push a tag matching the version: `git tag vX.Y.Z && git push origin vX.Y.Z`.
   This is the explicit publication authorization. The release workflow then:

   - refuses to continue unless the tagged commit is reachable from `main`.
     This catches a tag pushed on the wrong commit by mistake. It is not a
     control against a malicious tagger: a tag push runs the tagged commit's
     own copy of `release.yml`, which such a commit could edit. That is what
     the tag ruleset and the `pypi` environment's required reviewer (see
     below) are for;
   - re-checks tag, package, and changelog agreement;
   - runs lint, type-check, and the test suite on the tagged commit against
     the locked (`uv run --locked`) dependencies;
   - stamps the full tag ref and commit into both Python distributions;
   - proves wheel, source distribution, and committed Claude plugin have the
     same canonical skill manifest;
   - installs the wheel into a clean venv holding only the runtime
     dependencies pinned in `uv.lock` (exported and installed with
     `--require-hashes`), and checks that `skilldeck provenance --json`
     there reports the expected version, tag ref, commit, and skills;
   - builds and validates an SPDX 2.3 SBOM from that runtime-only install;
   - writes and verifies an exact `SHA256SUMS` file;
   - creates GitHub SLSA provenance and SBOM attestations;
   - publishes only the wheel and source distribution to PyPI with Trusted
     Publishing and its PEP 740 attestation;
   - creates the GitHub release from the same build bundle; and
   - downloads the public release again, verifies both channels, and proves a
     one-byte modification is rejected.

   Build, attestation, PyPI, and GitHub release permissions are isolated in
   separate jobs. No publish job rebuilds an artifact. Releases run one at a
   time (a workflow `concurrency` group, never cancelled in progress): a tag
   pushed during a release waits for it. GitHub keeps only one waiting run per
   group, so if a third tag arrives the earlier waiting run is cancelled;
   re-run it once the queue clears.

Before the first tag, an owner must configure the repository settings below and
the matching pending/trusted publisher on PyPI. These are external release
gates, not values committed to the repository. Do not create a tag until that
configuration has been read back and the release PR is frozen.

## Repository settings that cannot live in code

The release workflow checks what it can, but who may push a release tag, who
must approve the PyPI upload, and which checks must pass before a merge are
repository settings. Configure all three, and re-check them whenever
maintainers or CI jobs change:

- **Tag ruleset for `v*`.** *Settings → Rulesets* (under "Code and
  automation") *→ New ruleset → New tag ruleset*. Change the enforcement
  status from the default **Disabled** to **Active**, add a target tag pattern
  `v*`, and enable **Restrict creations**, **Restrict updates**, and
  **Restrict deletions**. Only the release maintainers belong in the bypass
  list, so nobody else can create, move, or delete a release tag.
- **`pypi` environment.** *Settings → Environments → `pypi`*:
  - **Deployment branches and tags** → **Selected branches and tags**, with a
    single rule of ref type **Tag** and pattern `v*`, so only a release tag
    can reach the publish job;
  - **Required reviewers** → the release maintainers, so a pushed tag never
    reaches PyPI without an explicit approval. Once there are two or more
    maintainers, also enable **Prevent self-review** so the person who pushed
    the tag cannot approve their own upload (with a single maintainer it would
    block every release); and
  - **uncheck** (deselect) **Allow administrators to bypass configured
    protection rules**. GitHub enables it by default, and leaving it on lets
    an administrator skip the required reviewer.

  The PyPI trusted publisher must name this repository's owner and name, the
  `release.yml` workflow, and the `pypi` environment (PyPI treats the
  environment as optional; set it so the gates above apply).
- **Required status checks on `main`.** In `main`'s branch protection rule or
  ruleset, require every CI job to pass before merging: `lint`, `build`,
  `zizmor`, each `test (3.x)` leg, `test-os (windows-latest)`,
  `test-os (macos-latest)`, and `test-lowest (3.10)` / `test-lowest (3.14)`.
  A CI job only blocks a merge once it is listed there, and the release gate
  above assumes that whatever reached `main` passed CI. Add new jobs to the
  list when they are introduced.

Consumer verification is documented in
[verifying-releases.md](verifying-releases.md).

## The consistency guard

`scripts/check_release_consistency.py` (pure stdlib) asserts:

- `pyproject` version **==** the newest dated CHANGELOG version — run on every PR
  by the `lint` job, and also by `tests/test_release_consistency.py` under
  `pytest`.
- on a tag push, the tag (minus the `v`) **==** the `pyproject` version — run by
  the release workflow before it builds or publishes. Only an exact `vX.Y.Z` or
  `refs/tags/vX.Y.Z` (no leading zeros) is accepted; anything else (for
  example `refs/tags/x/v0.3.0`, `v0.3.0rc1`, or `v0.04.0`, which PEP 440
  would publish as 0.4.0) is rejected outright.

Every script reads the version through `scripts/_pyproject.py`, which takes
`version` from the `[project]` table only (via `tomllib` on Python 3.11+, and a
`[project]`-scoped scan on 3.10), so a `version` key in another table can never
be mistaken for the package version.

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
