# Verifying a Skilldeck release

These checks authenticate where release artifacts came from, verify their
bytes, and show which canonical skills they contain. They apply after the first
tagged release is published; until then the README's source-checkout install
path remains the supported path.

## Download and verify the release bundle

Use a current GitHub CLI with the `gh attestation` command. Replace `vX.Y.Z`
with the release you intend to install.

```bash
TAG=vX.Y.Z
REPOSITORY=IcebergAI/skilldeck
mkdir -p release
gh release download "$TAG" --repo "$REPOSITORY" --dir release
(cd release && sha256sum --check SHA256SUMS)
TAG_COMMIT=$(gh api "repos/$REPOSITORY/commits/$TAG" --jq .sha)
```

`SHA256SUMS` covers exactly one wheel, one source distribution, and one SPDX
2.3 runtime SBOM. On macOS, use `shasum -a 256 --check SHA256SUMS` if GNU
`sha256sum` is unavailable.

For both the wheel and source distribution, verify GitHub's signed build
provenance and the attached SPDX predicate:

```bash
for ARTIFACT in release/*.whl release/*.tar.gz; do
  gh attestation verify "$ARTIFACT" \
    --repo "$REPOSITORY" \
    --signer-workflow IcebergAI/skilldeck/.github/workflows/release.yml \
    --source-ref "refs/tags/$TAG" \
    --source-digest "$TAG_COMMIT" \
    --deny-self-hosted-runners

  gh attestation verify "$ARTIFACT" \
    --repo "$REPOSITORY" \
    --signer-workflow IcebergAI/skilldeck/.github/workflows/release.yml \
    --source-ref "refs/tags/$TAG" \
    --source-digest "$TAG_COMMIT" \
    --deny-self-hosted-runners \
    --predicate-type https://spdx.dev/Document/v2.3
done
```

The first command proves the artifact was built by the tagged Skilldeck release
workflow at that exact commit. The second authenticates the SPDX document that
describes the wheel and source distribution.

## Verify the PyPI channel

PyPI Trusted Publishing supplies a separate PEP 740 publish attestation. Ask
PyPI for each exact release filename and verify the file it serves against its
provenance record:

```bash
for ARTIFACT in release/*.whl release/*.tar.gz; do
  BASENAME=$(basename "$ARTIFACT")
  uvx --from pypi-attestations==0.0.29 pypi-attestations verify pypi \
    --repository https://github.com/IcebergAI/skilldeck \
    "pypi:$BASENAME"
done
```

This independently downloads and verifies PyPI's wheel and source distribution
under the expected repository identity. The release workflow publishes those
files from the same bundle used for the GitHub release, checked against the
digests its build job recorded; no channel rebuilds them. After the upload it
downloads the files PyPI serves and compares their SHA-256 with those build
digests before it creates the GitHub release, so the wheel and source
distribution listed in `SHA256SUMS` are byte-for-byte the files on PyPI.

## Inspect installed content

After installing the verified wheel in an isolated environment:

```bash
skilldeck provenance
skilldeck provenance --json
skilldeck provenance --verify
```

Plain `skilldeck provenance` (with or without `--json`) reports the **claims
embedded at build time**: the package version, the exact tag and commit, and
each bundled skill's version and canonical SHA-256 identity, as recorded in
the packaged content manifest. It does not read the installed skill files, so
a modified install still reports the original identity.

`skilldeck provenance --verify` **checks** those claims: it re-hashes every
installed skill's `meta.yaml` and `skill.md`, and exits 1 with an error naming
each skill that no longer matches its recorded canonical digest, is missing,
has unexpected files next to it, or is (or holds) a symlink or junction in
place of its files. It combines with `--json`. It detects changes to
installed skill files; it cannot vouch for a package whose code was also
changed, since that code does the checking. Verify the wheel itself (the
steps above) before installing it.

A source checkout honestly reports the tag and commit as unavailable instead
of inventing a release identity.

`skilldeck catalog --json` reports the same distribution identity and canonical
digests together with each skill's metadata and deprecation state, and, like
`--verify`, recomputes every digest from the installed files and fails on a
mismatch. Releases do not attach the catalog separately; generate it from the
verified wheel. See [the skill catalog](catalog.md).

The Claude plugin contains the same generated content manifest at
`claude-plugin/.skilldeck/content-manifest.json`. Release CI recomputes the
canonical metadata, skill bodies, and rendered Claude files from the wheel,
source distribution, and tagged plugin tree before publication.

The plugin's `version` in `claude-plugin/.claude-plugin/plugin.json` is exactly
the release version (`X.Y.Z`) only for the content prepared for that release,
which includes the tagged commit (and `main` from the moment the release PR
merges until the next plugin content change). Otherwise the marketplace
serves `main` with a development version such as
`X.Y.(Z+1)-dev.sha256-<12 hex digits>` derived from its content digest, so
Claude Code offers every content change as an update. The release workflow
refuses to publish a tag whose plugin is a development snapshot. See
[releasing.md](releasing.md#claude-code-plugin-versions).

## What verification does and does not prove

- Checksums detect accidental corruption, but a checksum downloaded beside a
  mutable artifact does not authenticate its publisher by itself.
- GitHub and PyPI attestations authenticate producer identity and artifact
  integrity. They do not prove that the software is vulnerability-free.
- A modified artifact must fail its signed attestation. After publishing each
  tag, the release workflow runs the `gh attestation verify` command above on
  a wheel with bytes appended and requires it to fail with gh's "no
  attestations found" error; a failure for any other reason (network, auth)
  fails the release check instead of counting as a rejection.
