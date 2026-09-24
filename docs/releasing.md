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
- **The Claude Code plugin version follows its content.** It equals the
  project version only for the content prepared for that release; any other
  content on `main` ships as a development version such as
  `0.3.1-dev.sha256-8bc06884da4f`. See
  [Claude Code plugin versions](#claude-code-plugin-versions).

## CHANGELOG

[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Accumulate every
notable change under `## [Unreleased]` as you go. A dated `## [x.y.z] - DATE`
section is created at **release-prep** time (see below).

The **git tag is the source of truth for "published."** A dated section that has
no corresponding tag is *prepared but not yet shipped* — that is the current
state of the repo (nothing is tagged or on PyPI yet).

## Cutting a release

1. Choose the new version per SemVer.
2. Run `python scripts/prepare_release.py x.y.z` as the last change of the
   release PR. It bumps `pyproject.toml`, dates the `[Unreleased]` CHANGELOG
   section (leaving a fresh empty one above), runs `uv lock`, regenerates the
   Claude Code plugin tree (recording the plugin's current content as the
   release's, so `plugin.json` says exactly `x.y.z`), and re-runs the
   consistency guard.
   It validates everything first (a plain `X.Y.Z` with no leading zeros,
   newer than both the current version and the newest dated CHANGELOG
   section, an `[Unreleased]` section with at least one entry, no existing
   section for the version) and writes nothing if any check fails; if
   `uv lock` or plugin generation fails, or the plugin would not carry
   exactly `x.y.z`, it restores `pyproject.toml`, `CHANGELOG.md`, and
   `uv.lock` and exits non-zero.
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
   - proves the source distribution is exactly the tagged commit's files and
     the wheel exactly its `src/skilldeck` files (plus their generated
     metadata, checked against `pyproject.toml` and the wheel's `RECORD`),
     that both carry the same canonical skill manifest as the committed
     Claude plugin, and that the plugin is the prepared release rather than a
     development snapshot;
   - installs the wheel into a clean venv holding only the runtime
     dependencies pinned in `uv.lock` (exported and installed with
     `--require-hashes`), and checks that `skilldeck provenance --verify
     --json` there re-hashes the installed skills and reports the expected
     version, tag ref, commit, and skills;
   - builds and validates an SPDX 2.3 SBOM from that runtime-only install;
   - writes and verifies an exact `SHA256SUMS` file, and passes the SHA-256
     of every bundle file to the later jobs as a **job output**;
   - in each later job, checks the downloaded bundle against those digests
     before using it (`SHA256SUMS` travels inside the same artifact as the
     files it covers, so it cannot vouch for them across the handoff);
   - creates GitHub SLSA provenance and SBOM attestations;
   - publishes only the wheel and source distribution to PyPI with Trusted
     Publishing and its PEP 740 attestation;
   - downloads what PyPI serves for the release, compares its bytes with the
     build job's digests, and verifies PyPI's attestations, **before**
     creating the GitHub release. A PyPI upload can't be undone, so a
     mismatch here stops the release at PyPI (yank the files there) instead
     of spreading it to a GitHub release;
   - creates the GitHub release from the same build bundle; and
   - downloads the public release again, compares it with the build digests,
     verifies its attestations and identity, and proves that a modified wheel
     is rejected by the consumer's `gh attestation verify` command
     specifically because no attestation exists for its digest (any other
     failure, such as a network or auth error, fails the check instead of
     passing it).

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

## Claude Code plugin versions

The marketplace in `.claude-plugin/marketplace.json` points at
`./claude-plugin` in this repository. Claude Code resolves a relative-path
source against its local copy of the marketplace, and a marketplace added as
`IcebergAI/skilldeck` (no `ref`) tracks the repository's default branch. So
**`main` is the plugin channel**: no release tag exists yet (the first release
is tracked in #80), and pinning the marketplace to a tag would leave it with
nothing to install.

How Claude Code decides an installed plugin needs updating (checked against
the Claude Code docs, [Version
management](https://code.claude.com/docs/en/plugins-reference#version-management)
and [Version resolution and release
channels](https://code.claude.com/docs/en/plugin-marketplaces#version-resolution-and-release-channels),
and the plugin-update code bundled in the published
`@anthropic-ai/claude-code-linux-x64` 2.1.281 npm package):

- It resolves the version from `plugin.json`'s `version` first, and uses it
  as the cache key: "if the resolved version matches what a user already has,
  `/plugin update` and auto-update skip the plugin." Pushing new commits
  without changing the string has no effect.
- The comparison is plain string equality (plus equality of the cache
  directory named after the version, whose characters outside
  `[A-Za-z0-9._-]` become `-`). SemVer precedence is not consulted, so any
  different string counts as an update, even one that sorts lower.
- Omitting `version` would fall back to the git commit SHA of the
  marketplace, updating every user on every commit to `main`, and the
  version could no longer say which release a plugin is.

So the version is derived from the plugin content:

- `claude-plugin/.skilldeck/release.json` records the SHA-256 content digest
  of the plugin tree (every file but the record itself, with `plugin.json`'s
  `version` left out) at the moment the project version was bumped.
- While the plugin content still has that digest, `plugin.json` says exactly
  the project version (`0.4.0`). Any other content gets
  `<major>.<minor>.<patch+1>-dev.sha256-<first 12 hex digits of its digest>`,
  for example `0.4.1-dev.sha256-8bc06884da4f`: a SemVer pre-release that
  sorts after the last release and before the next one. Different content
  means a different string, so every change reaches existing installs, and
  reverting content restores its earlier version string.
- `scripts/build_plugin.py` records the digest when it sees a project version
  newer than the record (which `prepare_release.py` produces); it refuses a
  version older than the record, which would relabel today's content with an
  old string. The output depends only on the canonical skills, the project
  version, and the committed record, so `--check` and the pytest freshness
  guard stay deterministic, and a skill change committed without
  regenerating fails them.
- The release workflow runs `verify_distribution_identity.py
  --release-plugin`, which fails unless the tagged plugin is exactly the
  prepared release. CI on `main` checks the same derivation without
  requiring a release.

`0.3.0` was prepared but never tagged, and `main` changed the plugin content
under that version string, so the record starts with no content for `0.3.0`
and the plugin is on a development version until the first release, which
must therefore be newer than `0.3.0`. If a release PR changes the plugin
content after `prepare_release.py` ran, the plugin drops back to a
development version; before merging, restore the old record with
`git checkout origin/main -- claude-plugin/.skilldeck/release.json` and re-run
`python scripts/build_plugin.py` to record the final content.

## Generated trust files

- `src/skilldeck/_content_manifest.json` and
  `claude-plugin/.skilldeck/content-manifest.json` are generated together by
  `scripts/build_plugin.py`; never edit either by hand.
- `claude-plugin/.skilldeck/release.json` is the plugin release record
  described above; `scripts/build_plugin.py` writes it.
- `src/skilldeck/_build_metadata.json` is committed with unavailable source
  fields for development. `scripts/stamp_build_metadata.py` writes an exact
  `refs/tags/vX.Y.Z` plus full commit only inside the authorized tag workflow.
- `scripts/verify_distribution_identity.py` fails closed on archive traversal,
  links, duplicate members, malformed manifests, missing/orphaned skills, or
  any wheel/sdist/plugin digest mismatch. It reads the expected files from
  the checkout's `HEAD` with `git archive`, not from the working tree a build
  step could have edited, and requires the sdist to be exactly those files
  plus `PKG-INFO`, and the wheel exactly the `src/skilldeck` files plus
  `METADATA`, `WHEEL`, `entry_points.txt`, `RECORD`, and the license, with
  every file hashed correctly in `RECORD` and the requirements, entry point,
  and tag matching `pyproject.toml`. An added module or `.pth` file, changed
  code, or an added dependency fails it. Only the stamped
  `_build_metadata.json` may differ from the commit.
- `scripts/write_checksums.py` accepts exactly one wheel, one source
  distribution, and one SPDX document. It streams verification and rejects
  symlinks, malformed lines, duplicates, extras, and missing artifacts.
  `--digests` prints the bundle's digests as one line of JSON for a job
  output, and `--expect` checks a downloaded bundle against it.
- `scripts/verify_pypi_release.py` reads the release's files from PyPI's
  JSON API (`/pypi/skilldeck/<version>/json`), downloads each, and compares
  its SHA-256 with the build job's digests, retrying while PyPI's listing
  catches up.

The earlier tamper test also re-checked `SHA256SUMS` after appending bytes to
the wheel. That only showed that SHA-256 notices appended bytes, which the
unit tests cover, so it was dropped.
