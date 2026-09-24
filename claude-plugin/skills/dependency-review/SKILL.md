---
name: dependency-review
description: Review dependency changes in the diff for known vulnerabilities and supply-chain
  risk.
---

# Dependency Review

Review the **dependency changes on the current branch** — packages added,
upgraded, downgraded, or removed — for known vulnerabilities and supply-chain
risk. This covers the third-party-component side of OWASP Top 10:2025
[A03:2025 Software Supply Chain Failures](https://owasp.org/Top10/2025/A03_2025-Software_Supply_Chain_Failures/)
— vulnerable, unmaintained, or untrusted components, direct and transitive,
and malicious changes arriving through them — and ASVS 5.0 V15.1–V15.2
(component inventory from trusted repositories, remediation time frames,
dependency confusion). A03 also spans the build and distribution pipeline:
pair with `ci-workflow-review` for that and with `security-review` for the
rest of the application surface.

## Scope

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
2. Focus on dependency manifests and lockfiles, e.g.:
   - JS/TS — `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
   - Python — `pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`
   - Go — `go.mod`, `go.sum`; Rust — `Cargo.toml`, `Cargo.lock`
   - Java — `pom.xml`, `build.gradle`; Ruby — `Gemfile`, `Gemfile.lock`
   - Containers and CI — base-image and tool versions, for advisories only
     (their pins: step 4)
3. Diff old vs new versions to see exactly what changed. If automated tooling is
   available (`npm audit`, `pip-audit`, `osv-scanner`, `govulncheck`,
   `cargo audit`, `gh` advisory APIs), run it and cite the results; otherwise
   reason from the version changes and known advisories.
4. This skill owns package manifests and lockfiles; how CI steps and images
   are pinned belongs to `ci-workflow-review`, and IaC images and modules to
   `iac-review`. If the owner runs in the same review, leave its area to it;
   in a combined report, give each defect once, under the owner's classifier.

## What to look for

- **Known vulnerabilities** — does an added or upgraded package (or a transitive
  dependency pulled in by the lockfile change) have a CVE/GHSA advisory? Does the
  resolved version fall in the affected range? Is the fix available in a later
  release?
- **Outdated / unmaintained** — a pinned version far behind upstream, or a
  package with no recent releases, no active maintainers, or no security
  fixes for the line in use (end-of-life).
- **Supply-chain red flags**:
  - **Typosquatting / confusion** — a name suspiciously close to a popular
    package, or an internal name resolvable from a public index (dependency
    confusion).
  - **Provenance** — source switched to a fork, a git URL, a non-canonical
    registry, or a plain-HTTP index; signature or attestation checks
    dropped; install/postinstall scripts newly introduced (the entry point
    of the 2025 Shai-Hulud npm worm).
  - **Trust footprint** — a new direct dependency that pulls a large transitive
    tree, or a tiny utility added for trivial functionality.
- **Version hygiene** — mutable pins (`*`, `latest`, or a range no committed
  lockfile pins) or ranges loosened (`^`/`~`) where exact pins are the norm
  here; a lockfile change with no corresponding manifest change (or vice
  versa); a downgrade that re-introduces a fixed CVE.
- **Licensing** — a new dependency under a license incompatible with the
  project's (e.g. GPL pulled into a permissively-licensed codebase).
- **Integrity** — missing or changed lockfile hashes/checksums.

## Output

Report each finding as a single list item:

- **[severity] advisory ID or concern** — `package old→new`
  **Issue:** the advisory (CVE/GHSA) and affected range, or the specific
  supply-chain concern; note whether the package is a direct or transitive dependency.
  **Fix:** upgrade to the patched version, pin, swap package, or remove; note if no
  fixed version exists yet.

Rate `severity` on the shared severity rubric, impact × likelihood:
**critical** — high impact (code execution, auth bypass, stolen credentials or
bulk data, data loss, an outage), readily triggered (by anyone who can reach
it, or in routine operation); **high** — high impact behind a common
precondition (an authenticated user, a collaborator, a routine failure), or
medium impact (limited exposure, degraded service) readily triggered;
**medium** — high impact only under an unusual precondition, medium impact
behind a common one, or low impact readily triggered (a weakened defense
anyone can reach); **low** — medium impact only under an unusual
precondition, or low impact behind any precondition (most defense in depth
and hygiene).
Here: **critical** — an advisory that is known-exploited or critical in the
resolved version range, or a clear malicious-package signal; **high** — a
high-severity advisory, or a serious provenance concern (a switch to a fork,
a personal repo, or a non-canonical registry or index; newly introduced
install scripts); **medium** — outdated or unmaintained packages, lockfile
drift, or a mutable pin (classified `Mutable pin`). A provenance finding
already covers its source's floating ref, so don't file a pin for it too; a
git source from the usual owner that lacks a commit SHA is a `Mutable pin`.
The classifier is the advisory ID (e.g. `CVE-2024-12345`, `GHSA-…`) or the
supply-chain concern (e.g. `Typosquatting`); the location slot names the
package and its version change instead of a `file:line`. Order findings by
severity, highest first, and keep one issue per finding. For example:

- **[high] Provenance** — `left-pad 1.3.0→git+https://github.com/someuser/left-pad`
  **Issue:** the dependency now resolves to a personal fork instead of the
  registry release, so an unvetted owner can change its contents with no version
  bump or registry review. Direct dependency.
  **Fix:** pin back to the registry release, or vendor the fork at a reviewed
  commit hash.

Verify before reporting: **never cite an advisory ID you have not verified**
from tool output or a fetched advisory page — do not reproduce CVE/GHSA numbers
from memory; if you cannot verify, describe the concern and state that advisory
lookup was not possible. Re-check each remaining candidate against the manifest
and lockfile and drop any you cannot substantiate. Prefer the few findings that
matter; if more than ~10 survive, report the ones worth a human's time and
summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed origin/main...HEAD (2 manifests): 1 finding, high.` If the diff
touches no dependency manifest or lockfile, say so and stop. If the dependency
changes are clean, say so explicitly.
