# Dependency Review

Review the **dependency changes on the current branch** — packages added,
upgraded, downgraded, or removed — for known vulnerabilities and supply-chain
risk. This covers OWASP Top 10
[A06:2021 Vulnerable and Outdated Components](https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/)
and ASVS V15 (Secure Coding & Architecture); pair it with `security-review` for
the rest of the application surface.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`).
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

For each finding report:

- **Severity** (critical / high / medium / low)
- **Package** and the **version change** (`old -> new`), direct or transitive
- **Issue** — the advisory ID (CVE/GHSA) or the specific supply-chain concern
- **Recommendation** — concrete fix: upgrade to the patched version, pin, swap
  package, or remove; note if no fixed version exists yet

If the dependency changes are clean, say so explicitly. If the diff touches no
dependencies, state that rather than reviewing application code — that is the job
of `security-review`.
