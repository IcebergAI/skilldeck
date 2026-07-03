# Dependency Review

Review the **dependency changes on the current branch** — packages added,
upgraded, downgraded, or removed — for known vulnerabilities and supply-chain
risk. This covers OWASP Top 10
[A06:2021 Vulnerable and Outdated Components](https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/)
and ASVS V15 (Secure Coding & Architecture); pair it with `security-review` for
the rest of the application surface.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Focus on dependency manifests and lockfiles, e.g.:
   - JS/TS — `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
   - Python — `pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`
   - Go — `go.mod`, `go.sum`; Rust — `Cargo.toml`, `Cargo.lock`
   - Java — `pom.xml`, `build.gradle`; Ruby — `Gemfile`, `Gemfile.lock`
   - Containers — `Dockerfile` base images; CI — pinned action/tool versions
3. Diff old vs new versions to see exactly what changed. If automated tooling is
   available (`npm audit`, `pip-audit`, `osv-scanner`, `govulncheck`,
   `cargo audit`, `gh` advisory APIs), run it and cite the results; otherwise
   reason from the version changes and known advisories.

## What to look for

- **Known vulnerabilities** — does an added or upgraded package (or a transitive
  dependency pulled in by the lockfile change) have a CVE/GHSA advisory? Does the
  resolved version fall in the affected range? Is the fix available in a later
  release?
- **Outdated / unmaintained** — a pinned version far behind upstream, or a
  package with no recent releases and no active maintainers.
- **Supply-chain red flags**:
  - **Typosquatting / confusion** — a name suspiciously close to a popular
    package, or an internal name resolvable from a public index (dependency
    confusion).
  - **Provenance** — source switched to a fork, a git URL, or a non-canonical
    registry; install/postinstall scripts newly introduced.
  - **Trust footprint** — a new direct dependency that pulls a large transitive
    tree, or a tiny utility added for trivial functionality.
- **Version hygiene** — unpinned or loosened ranges (`*`, `latest`, `^`/`~`
  where exact pins are the norm here); a lockfile change with no corresponding
  manifest change (or vice versa); a downgrade that re-introduces a fixed CVE.
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

`severity` reflects exposure: **critical** — an advisory that is known-exploited
or critical in the resolved version range, or a clear malicious-package signal;
**high** — a high-severity advisory, or a serious provenance concern (fork or
git source, newly introduced install scripts); **medium** — outdated or
unmaintained packages, loosened pins, lockfile drift; **low** — hygiene and
licensing nits. The classifier is the advisory ID (e.g. `CVE-2024-12345`,
`GHSA-…`) or the supply-chain concern (e.g. `Typosquatting`); the location slot
names the package and its version change instead of a `file:line`. Order
findings by severity, highest first, and keep one issue per finding. For example:

- **[high] Provenance** — `left-pad 1.3.0→git+https://github.com/someuser/left-pad`
  **Issue:** the dependency now resolves to a personal fork instead of the
  registry release, so its contents can change without a version bump and bypass
  registry review. Direct dependency.
  **Fix:** pin back to the registry release, or vendor the fork at a reviewed
  commit hash.

Verify before reporting: **never cite an advisory ID you have not verified**
from tool output or a fetched advisory page — do not reproduce CVE/GHSA numbers
from memory; if you cannot verify, describe the concern and state that advisory
lookup was not possible. Re-check each remaining candidate against the manifest
and lockfile and drop any you cannot substantiate.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (2 manifests): 1 finding, high.` If the dependency changes
are clean, say so explicitly. If the diff touches no dependencies, state that
rather than reviewing application code — pair with `security-review` for that.
