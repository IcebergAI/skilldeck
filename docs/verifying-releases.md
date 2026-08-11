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
files from the same checksum-verified bundle used for the GitHub release; no
channel rebuilds them.

## Inspect installed content

After installing the verified wheel in an isolated environment:

```bash
skilldeck provenance
skilldeck provenance --json
```

The command reports the package version, exact tag and commit embedded at build
time, and each bundled skill's version and canonical SHA-256 identity. A source
checkout honestly reports the tag and commit as unavailable instead of
inventing a release identity.

The Claude plugin contains the same generated content manifest at
`claude-plugin/.skilldeck/content-manifest.json`. Release CI recomputes the
canonical metadata, skill bodies, and rendered Claude files from the wheel,
source distribution, and tagged plugin tree before publication.

## What verification does and does not prove

- Checksums detect accidental corruption, but a checksum downloaded beside a
  mutable artifact does not authenticate its publisher by itself.
- GitHub and PyPI attestations authenticate producer identity and artifact
  integrity. They do not prove that the software is vulnerability-free.
- A modified artifact must fail both its checksum and its signed attestation.
  The release workflow performs that negative test after publishing each tag.
