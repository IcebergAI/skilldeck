# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project version
(`pyproject.toml`) tracks the installer; individual skills carry their own
`version` in `meta.yaml`, noted below.

## [Unreleased]

### Security

- CI/release workflows pin all GitHub Actions to full commit SHAs (tag noted in
  a comment), and a Dependabot config keeps the pins and dev dependencies
  current (#34).

### Added

- `scripts/prepare_release.py <version>` automates release prep: bumps
  `pyproject.toml`, dates the `[Unreleased]` CHANGELOG section, re-locks,
  regenerates the plugin tree, and re-runs the consistency guard
  (`docs/releasing.md` updated to make it the documented path) (#35).
- The repo is now a Claude Code plugin marketplace (#31):
  `/plugin marketplace add IcebergAI/skilldeck` then
  `/plugin install skilldeck@skilldeck` installs all skills with no Python
  tooling. The committed plugin tree (`.claude-plugin/marketplace.json` +
  `claude-plugin/`) is generated from the canonical skills by
  `scripts/build_plugin.py`; a pytest freshness guard fails if it drifts.
- Cursor and GitHub Copilot adapters (#30). Cursor installs agent-requested
  rules to `.cursor/rules/<name>.mdc` (`description` + `alwaysApply: false`);
  Copilot installs prompt files to `.github/prompts/<name>.prompt.md`, run
  with `/<name>` in chat. Both are project-scope only — neither tool has a
  stable filesystem location for user-level config — enforced by a new
  per-adapter `scopes` attribute. All skills add the two agents to
  `supported-agents` (patch version bumps).
- `install`/`uninstall` accept `--agent` multiple times, or `--agent all`, to
  target several agents in one command; `skilldeck show <name>` prints a
  skill's body (or, with `--agent`, the rendered per-agent output) before
  installing (#29).
- Installed skills are now stamped with a `skilldeck` comment recording the
  skill name, version, and a content hash. New commands build on it:
  `skilldeck status --agent <a>` shows installed vs bundled versions
  (up to date / stale / modified locally / unmanaged, plus orphans of skills no
  longer bundled) and `skilldeck update --agent <a>` refreshes stale installs
  (#27).
- `install` no longer silently overwrites: a destination file with local
  modifications — or one skilldeck didn't write — is refused unless `--force`
  is given; `update` likewise skips modified installs without `--force` (#28).
  Note: installs made by skilldeck ≤ 0.3.0 carry no stamp, so the first
  reinstall over them needs `--force` once.
- Structural lint tests (`tests/test_skill_structure.py`) asserting every
  bundled skill body carries the standardized elements: a Scope section with
  the uncommitted-changes fallback, severity anchors, a worked example, the
  verify-before-reporting instruction, and the one-line report header (#33).

### Changed

- `dependency-review` (0.2.1): advisory-ID guard rephrased to lead with the
  shared "Verify before reporting" instruction so the structural lint can
  assert it uniformly.

- All seven skills refined to better guide review agents: diff determination now
  covers uncommitted/untracked changes and the on-base-branch case; agents are
  told to read the whole function around each hunk (not just the diff) and to
  verify each candidate finding before reporting it; severity levels get
  domain-specific anchors; each Output section gains a worked example finding, a
  one-line report header (`Reviewed <base>..HEAD (N files): …`), and
  finding-count discipline. Per-skill additions: language-idiom caveat
  (`code-smells` 0.2.0), never-cite-unverified-advisory-IDs guard
  (`dependency-review` 0.2.0), a Scope section with write/review modes
  (`logging` 0.2.0), respect-existing-safety-tooling step (`migration-review`
  0.2.0), check-stack-defaults step (`resilience-review` 0.2.0), source→sink
  tracing for injection findings (`security-review` 0.3.0), and
  regression-test-must-fail-without-the-fix verification (`test-review` 0.2.0).
- Kiro adapter now renders skills with `inclusion: manual` frontmatter: Kiro
  steering documents are included in every interaction by default, which is
  wrong for on-demand review prompts.

### Fixed

- A `meta.yaml` that parses to something other than a YAML mapping now fails
  with a clean `error:` message instead of a `TypeError` traceback (which also
  broke every command, since discovery loads all skills).
- Install failures caused by an unwritable destination (e.g. `.claude` existing
  as a regular file) now raise a clean error instead of an unhandled traceback.
- Uninstalling a skill named after a shared install directory (a Codex skill
  named `prompts`, a Kiro skill named `steering`) no longer removes that shared
  directory when it becomes empty: per-skill directory cleanup is now declared
  by the adapter (`creates_skill_dir`) instead of inferred from the name.
- `scripts/check_release_consistency.py` now selects the highest dated
  CHANGELOG version (compared numerically) rather than assuming the newest
  section appears first in the file.

### Removed

- Dead `skilldeck.registry.get_skill` helper (unused, and it skipped
  `supported-agents` validation).

### Added

- `docs/releasing.md` documenting the versioning and release procedure, plus
  `scripts/check_release_consistency.py` — a stdlib guard that asserts the
  `pyproject` version, the newest dated CHANGELOG section, and (on a tag push) the
  release tag all agree. Wired into CI (`lint` job and `pytest`) and the release
  workflow (before publish), so version/CHANGELOG/tag drift fails fast.

## [0.3.0] - 2026-06-27

### Added

- `resilience-review` skill (0.1.0) — reviews pending changes for fault tolerance
  when dependencies are slow, failing, or overloaded (timeouts, retries/backoff,
  circuit breakers, resource leaks, backpressure, graceful degradation). Drawn
  from the *Release It!* stability patterns and the Google SRE book; kept
  pattern-level and tooling-agnostic.
- `migration-review` skill (0.1.0) — reviews database schema and data migrations
  for safety under a live, rolling deploy (backward compatibility / expand-contract,
  blocking locks, unbatched backfills, constraint validation, reversibility,
  transactional DDL). Drawn from the expand/contract pattern and zero-downtime
  migration guidance; kept engine- and tooling-agnostic.

## [0.2.0] - 2026-06-27

### Security

- The Claude adapter now serializes skill frontmatter with `yaml.safe_dump`
  instead of string interpolation, so a name/description containing newlines or
  YAML metacharacters cannot inject extra frontmatter keys into the rendered
  `SKILL.md`.
- `install` refuses to write through a symlink at the destination, preventing a
  pre-placed symlink from redirecting the write to an arbitrary file.
- Dropped Python 3.9 support (`requires-python` now `>=3.10`) to resolve
  Dependabot alert GHSA-6w46-j5rx-g56g / CVE-2025-71176 (pytest insecure tmpdir
  handling): the fix lands only in pytest 9.0.3+, which requires Python 3.10+,
  so the 3.9 test matrix was the sole remaining resolution pinning a vulnerable
  pytest. Python 3.9 reached end-of-life in October 2025. The dev `pytest` floor
  is now `>=9.0.3`; the CI matrix and trove classifiers are 3.10–3.14.

### Added

- Continuous integration (GitHub Actions): ruff lint/format, mypy (strict on
  `src`), a pytest matrix across Python 3.9–3.14, and a build check that the
  skills are bundled into the wheel.
- Release workflow that publishes to PyPI via Trusted Publishing (OIDC) on
  version tags.
- `logging` skill (0.1.0) — guidance for adding and reviewing application
  logging following the OWASP Logging Cheat Sheet.
- `code-smells` skill (0.1.0) — reviews pending changes for code smells
  (refactoring.guru catalog) and suggests refactorings.
- `dependency-review` skill (0.1.0) — reviews dependency/lockfile changes for
  known vulnerabilities and supply-chain risk (OWASP A06, ASVS V15).
- `test-review` skill (0.1.0) — reviews pending changes for adequate, meaningful
  test coverage and flags weak, misleading, or flaky tests.
- `docs/finding-output.md` — canonical finding format shared by all review
  skills, so findings can be sorted, deduplicated, and posted as PR comments
  without per-skill parsing; referenced from `docs/authoring-skills.md`.

### Changed

- **Renamed the project `skillful` → `skilldeck`** to avoid a PyPI name
  collision with an unrelated package. The distribution, `import` package, and
  console command are all now `skilldeck` (e.g. `uvx skilldeck`,
  `skilldeck list`).
- `security-review` skill (0.1.0 → 0.2.0) — review checklist realigned to the
  OWASP ASVS 5.0 categories (V1–V16) with assurance levels (L2 default); findings
  now include an ASVS category.
- `security-review` skill (0.2.0 → 0.2.1) — added the ASVS 5.0 **V17 WebRTC**
  category (scoped to changes that touch WebRTC).
- `code-smells` skill (0.1.0 → 0.1.1) — added the **Incomplete Library Class**
  coupler smell to complete the refactoring.guru catalog.
- `logging` skill (0.1.0 → 0.1.1) — added OWASP Logging Cheat Sheet guidance on
  synchronizing time across sources and protecting log integrity (tamper-evident,
  append-only storage; restricted access).
- All review skills (`security-review` 0.2.1 → 0.2.2, `code-smells` 0.1.1 →
  0.1.2, `logging` 0.1.1 → 0.1.2, `dependency-review` 0.1.0 → 0.1.1, `test-review`
  0.1.0 → 0.1.1) — conformed every `## Output` section to the shared finding
  format (`[severity] classifier — location` + Issue + Fix) documented in
  `docs/finding-output.md`.
- `skilldeck list` groups skills by category (the `category` field was previously
  required but never surfaced).
- `install`/`uninstall` no longer re-parse every skill once per requested name;
  skills are discovered a single time per invocation.
- Filled out packaging metadata for PyPI (authors, keywords, trove classifiers,
  project URLs) and fixed the stale `Skillful` copyright in `LICENSE`.

### Fixed

- The installed `skilldeck` console command now routes through `main()`, so a
  malformed skill reports a clean `error: …` message instead of a traceback (the
  entry point previously bypassed the error handler).
- `uninstall` removes the now-empty per-skill directory it created (e.g. Claude's
  `.claude/skills/<name>/`) instead of leaving it behind; shared directories are
  left untouched.
- `Skill` is now hashable (its `supported-agents` is stored as a tuple), so the
  frozen dataclass can be used in sets and as dict keys.
- `supported-agents` entries are validated against the known adapters at the CLI
  boundary; a typo'd agent name now fails loudly instead of silently never
  installing.
- Updated stale `Skillful` references to `skilldeck` and made package metadata the
  single source of truth for the version (dropped the duplicated `__version__`
  literal).

## [0.1.0]

### Added

- Initial `skilldeck` CLI: `list`, `install`, `uninstall`.
- Agent adapters for Claude, Codex, and Kiro.
- `security-review` skill (0.1.0).
