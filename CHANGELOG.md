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

- `authentication-review` skill (0.1.0) — reviews authentication changes in
  depth: password storage and policy, recovery/reset flows, MFA bypass and OTP
  handling, session fixation and cookie hardening, JWT/API-token verification
  (alg confusion, key selection), OAuth 2.0 (PKCE, `state`, `redirect_uri`
  exact match, deprecated grants), OIDC (`nonce`, `iss`+`sub` identity, JWKS
  trust), SAML (assertion vs response signatures, XSW, replay/conditions), and
  LDAP sign-in (empty-password bind, unchecked bind result). Classified
  against OWASP ASVS 5.0 (V6/V7/V9/V10, with V11/V3 for KDF and cookie
  findings) with patterns from RFC 9700, NIST SP 800-63B, and the OWASP
  Authentication, Password Storage, Session Management, MFA, Forgot Password,
  and SAML Security cheat sheets. Pairs with `security-review` (bumped to
  0.3.2 for the reciprocal cross-reference), which keeps breadth coverage.
  Ships with OAuth (hand-rolled code flow missing `state`/PKCE) and SAML
  (response-envelope-only signature check + raw-document `NameID` read) eval
  fixtures.
- `ci-workflow-review` skill (0.2.0) — reviews CI/CD pipeline changes for
  injection and poisoned pipeline execution (untrusted `github.event` /
  GitLab predefined-variable interpolation, `pull_request_target` + head
  checkout, fork MR pipelines), credential and token scope
  (`GITHUB_TOKEN` permissions, `CI_JOB_TOKEN` allowlist, masked/protected
  variables), unpinned third-party steps and `include:`s, artifact/cache
  integrity, and runner exposure (self-hosted runners, GitLab privileged
  Docker/DinD and shell executors). Classified against the OWASP Top 10 CI/CD
  Security Risks (CICD-SEC-1–10) with patterns from GitHub's Actions hardening
  guide and GitLab's pipeline/job-token/runner security guidance. Ships with
  GitHub and GitLab eval fixtures (`workflow_run` artifact poisoning through
  `$GITHUB_ENV` plus a tag-pinned third-party action; a privileged DinD runner
  plus MR-title injection in a fork-reachable job).
- `iac-review` skill (0.1.0) — reviews infrastructure-as-code changes
  (Terraform, CloudFormation, Kubernetes/Helm, Dockerfiles) for network
  exposure, wildcard IAM, secrets in code/state, missing encryption, container
  hardening per the Kubernetes Pod Security Standards and the OWASP Docker
  cheat sheet, and stateful-resource change safety; anchored to CIS benchmark
  baselines. Ships with an eval fixture (wildcard S3 policy on an app role).
- Golden-diff eval harness (`evals/`) (#32): seven fixtures — one per skill —
  each a tiny repo whose diff contains a planted defect (path traversal,
  one-step column rename, assertion-free test, retry without backoff on a
  non-idempotent POST, log injection, dependency confusion, duplicate code).
  `python evals/run_evals.py` builds each repo,
  installs the skill, invokes an agent (default: Claude CLI), and scores the
  report: plants must be found and total findings must stay under a cap. Runs
  manually (paid API); CI validates fixture structure only.
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
  `supported-agents` (patch version bumps). These formats are now the
  `cursor-rule` and `copilot-prompt` legacy adapters; `cursor` and `copilot`
  install `SKILL.md` folders at both scopes (see Changed, #100).
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
  reinstall over them needs `--force` once, and so does uninstalling them
  (#95).
- Structural lint tests (`tests/test_skill_structure.py`) asserting every
  bundled skill body carries the standardized elements: a Scope section with
  the uncommitted-changes fallback, severity anchors, a worked example, the
  verify-before-reporting instruction, and the one-line report header (#33).
- The release workflow now gates publication (#108): a `verify` job fails
  unless the tagged commit is reachable from `main` and runs lint, type-check,
  and the test suite on it before anything is built. That catches a tag pushed
  on the wrong commit by mistake; because a tag push runs the tagged commit's
  own workflow file, the controls against a malicious tagger are repository
  settings. Releases are serialized by a `concurrency` group that never
  cancels a running release. `docs/releasing.md` documents the repository
  settings that cannot live in code: a `v*` tag ruleset restricting
  creation/update/deletion, a `pypi` environment limited to `v*` tags with
  required reviewers and no administrator bypass, and the CI jobs to make
  required status checks on `main`.
- Release builds are locked (#110): hatchling is pinned to `>=1.27,<2` in
  `[build-system]` (CI builds with both hatchling 1.27.0 and the newest release
  and checks that both builds carry the same identity), every `uv run`/`uv sync`
  in CI and the release workflow except the dependency-floor job passes
  `--locked` (a stale `uv.lock` now fails instead of re-resolving), and
  the SBOM venv is built from `uv export` of `uv.lock` installed with
  `--require-hashes` (the wheel with `--no-deps`), so the attested SBOM
  describes the locked runtime rather than a fresh resolve. Dependabot waits
  7 days (`cooldown`) before proposing a new release of an action or
  dependency.

- Release verification steps now fail for the right reasons (#109). The build
  job passes the SHA-256 of every bundle file to later jobs as a job output
  (`write_checksums.py --digests`), and the attest, PyPI, GitHub-release, and
  readback jobs check their download against it (`--expect`) instead of
  against the `SHA256SUMS` carried inside the same artifact. A new
  `verify-pypi` job downloads what PyPI serves (`scripts/verify_pypi_release.py`
  via PyPI's JSON API), compares the bytes with the build digests and checks
  PyPI's attestations before the GitHub release is created. The tamper check
  now passes only when `gh attestation verify` rejects the modified wheel
  with "no attestations found", so a network or auth error fails it; the
  checksum half of that check, which only showed that SHA-256 notices
  appended bytes, is gone. `verify_distribution_identity.py` compares the
  distributions with the tagged commit (`git archive` of the expected commit,
  which must be the checkout's `HEAD`): the sdist must
  be exactly the committed files plus `PKG-INFO`, and the wheel exactly the
  committed `src/skilldeck` files plus its `.dist-info`, with every file
  correctly hashed in `RECORD` and `METADATA` requirements (environment
  markers included), extras, `entry_points.txt`, and the `WHEEL` tag matching
  `pyproject.toml`, so an extra module or `.pth` file, changed code, or an
  added, dropped, or re-scoped dependency fails. Its suffix matching is
  anchored at `/` path boundaries. `verify_pypi_release.py` retries a
  download cut short mid-read as well as connection errors.

### Changed

- Five review skills cover defect classes their checklists missed, each
  cited to a fetched source (#104):
  - `ci-workflow-review` 0.4.0: newline injection through writes to
    `$GITHUB_ENV`, `$GITHUB_OUTPUT`, and `$GITHUB_PATH`; `${{ }}` in
    `actions/github-script` `script:` as JavaScript injection; label,
    `issue_comment`, and environment-approval gates that check out a mutable
    PR ref (time-of-check/time-of-use); `secrets: inherit`; `actions/checkout`
    without `persist-credentials: false`; and a step not to re-flag what a
    blocking zizmor or actionlint job already enforces. A new eval fixture,
    `ci-workflow-review-env-injection`, plants a `workflow_run` job that
    writes a fork-controlled artifact into `$GITHUB_ENV` after a checkout
    that persists its token.
  - `iac-review` 0.3.0: CI OIDC trust wider than one repository and ref (no
    `sub` condition, since `aud` alone admits any repository, or a wildcard
    on an AWS role; no attribute condition on a GCP pool; a broad Azure
    flexible federated credential), with a role any GitHub repository can
    assume rated critical; EC2 instances and launch templates that don't require IMDSv2;
    and audit logging (CloudTrail, GCP audit configs, Azure activity-log
    export) switched off or narrowed.
  - `migration-review` 0.4.0: MySQL/MariaDB metadata-lock waits and
    `lock_wait_timeout`, with gh-ost and pt-online-schema-change for large
    rebuilds; the `INVALID` index a failed `CREATE INDEX CONCURRENTLY` leaves
    behind; Rails column caching on a drop (`ignored_columns` first); `int` →
    `bigint` primary keys; and PostgreSQL `NOT VALID` then `VALIDATE` for
    CHECK and foreign-key constraints, and for not-null constraints on
    PostgreSQL 18.
  - `security-review` 0.5.0: SSTI (1.3.7, 1.3.5), ReDoS (1.2.9, 1.3.12), XXE
    (1.5.1), open redirects (3.7.2), prototype pollution (15.3.6),
    business-logic races (2.3.4), and TOCTOU on shared resources (15.4.2)
    named with their ASVS 5.0 requirements; `llm-integration-review` listed
    as the owner of LLM and agent integrations.
  - `dependency-review` 0.4.0: `composer.lock`, `packages.lock.json`,
    `Package.resolved`, and `bun.lock`/`bun.lockb`; Go `replace` directives;
    pip `--extra-index-url` dependency confusion; and malware signals (new
    install scripts, a brand-new package or version, a release from a new
    maintainer or owner, a release with less trust evidence than earlier
    ones, obfuscated code).
- All review skills now rate severity on one shared rubric and agree on
  shared defects (#103). `docs/finding-output.md` defines the rubric as
  impact × likelihood, following the OWASP Risk Rating Methodology's severity
  matrix. Every skill's `## Output` copies its one-paragraph form word for
  word and keeps a short list of domain anchors. Critical now means only a
  security exploit, data loss, or an outage: `code-smells` and `test-review`
  top out at high (a missing test is no longer critical), and
  `migration-review` and `resilience-review` use critical only for an outage
  or data loss. A live credential committed to the repository or written to
  logs or CI output that others can read is critical in `security-review`,
  `logging`, `iac-review`, and `ci-workflow-review` alike, and its Fix must
  revoke and rotate it (OWASP Secrets Management Cheat Sheet). A mutable pin (a
  tag or branch instead of a SHA or digest, or an unlocked package range) is
  medium everywhere, down from high for CI steps in privileged jobs; a GitLab
  include or component pinned to a tag in a project outside your org now
  counts as one. Each kind of pin has one owner: `ci-workflow-review` for CI
  config (classified `CICD-SEC-3 Dependency Chain Abuse`), `iac-review` for
  IaC and Kubernetes images and Terraform modules (it gains a Mutable pins
  checklist citing the Kubernetes and Terraform docs), and `dependency-review`
  for package manifests; the others defer to the owner.
- A new "Which skill owns what" section in `docs/finding-output.md` names
  the owner of each overlapping area: `authentication-review` for ASVS V6,
  V7, V9, and V10, `logging` for V16, and `ci-workflow-review`,
  `dependency-review`, and `iac-review` for pipeline, supply-chain, and
  infrastructure config. Each overlapping skill says to leave the owner's area
  to it when both run, and to report each defect once, under the owner's
  classifier (#103).
- Review skills share the same scope and report wording (#103). Each one
  diffs against a freshly fetched remote base (`git fetch`, then
  `git diff origin/<base>...HEAD`), lists untracked files with
  `git ls-files --others --exclude-standard`, and uses the same three-dot
  range in its report header. Each says to "say so and stop" when the change
  touches nothing in its area. `logging` gains a proper `## Output` heading,
  `dependency-review` gains the ~10-findings cap, and `docs/finding-output.md`
  now lists `resilience-review` and `migration-review` and allows one or two
  sentences for Issue/Fix. `tests/test_skill_structure.py` enforces the
  Output heading, the findings cap, the rubric (compared to the doc), the
  nothing-in-scope line, the fetch/untracked commands, three-dot ranges, and
  the high cap. Skill versions: `security-review` 0.4.0,
  `authentication-review` 0.2.0, `ci-workflow-review` 0.3.0, `code-smells`
  0.3.0, `dependency-review` 0.3.0, `iac-review` 0.2.0, `logging` 0.3.0,
  `migration-review` 0.3.0, `resilience-review` 0.3.0, `test-review` 0.3.0.
- **Breaking:** the `codex`, `copilot`, `cursor` and `kiro` adapters now
  install [Agent Skills](https://agentskills.io/specification) folders, the
  format every supported agent reads today, instead of prompt, rule and
  steering files (#100, #99). Each writes the same `SKILL.md` as the `claude`
  adapter (whose output is unchanged) into the agent's own skills folder:
  `.agents/skills/<name>/` for Codex (`~/.agents/skills/` globally),
  `.github/skills/` for Copilot (`~/.copilot/skills/`), `.cursor/skills/` for
  Cursor (`~/.cursor/skills/`) and `.kiro/skills/` for Kiro
  (`~/.kiro/skills/`). Copilot and Cursor now support `--scope global`.
  Codex needs 0.95.0 or later and Copilot in VS Code 1.109 or later; for
  older agents, the previous Copilot, Cursor and Kiro formats remain as
  opt-in legacy adapters (see Added). Existing installs in the old locations
  are left alone: move them with `skilldeck migrate`. The shared rendering
  lives in a new `SkillMdAdapter` base; an adapter now declares a project
  folder and a `UserDir` for its global folder instead of one path relative
  to `$HOME` or the project, and `targets.base_dir` is replaced by
  `project_base` and `UserDir`. `docs/adapters.md` gives each agent's
  locations, minimum versions and vendor sources, which folders each agent
  also reads, and a recommended setup that avoids duplicate skills.
- Global installs follow the variable that moves an agent's config directory
  (#98): `CLAUDE_CONFIG_DIR` (Claude Code then reads personal skills only from
  `$CLAUDE_CONFIG_DIR/skills`), `COPILOT_HOME` (Copilot CLI) and `KIRO_HOME`
  (Kiro CLI; it also moves `kiro-steering`). `CODEX_HOME` does not move
  `~/.agents/skills`, so the Codex adapter ignores it. An empty
  `CLAUDE_CONFIG_DIR` is refused with an error, because Claude Code resolves
  it against its working directory rather than falling back to `~/.claude`;
  empty `COPILOT_HOME` and `KIRO_HOME` count as unset, and a relative value of
  any of them is refused. The error is reported for that agent only.
- `status` and `update` accept `--agent` more than once, or `--agent all`, like
  `install` and `uninstall`. When more than one agent is selected, each
  agent's results appear under a header (#98).
- `--agent all` now means every agent that supports the chosen `--scope`. An
  agent without a location at that scope is skipped with a note, where
  `install` used to report an error for each skill. Naming such an agent
  explicitly is still an error, even alongside `all` (#98). Every native
  adapter now supports both scopes. `all` selects only the five native
  adapters; a legacy adapter (the project-only `copilot-prompt` and
  `cursor-rule`, and `kiro-steering`) runs only when named, even alongside
  `all`.
- Installs are atomic. The file is written to a temporary file in the same
  directory and then renamed into place with `os.replace`, so an interrupted
  install can't leave a half-written skill behind. The temporary file is
  removed if anything fails, a new file gets the usual umask-based
  permissions, and an overwritten file keeps its own, plus owner read access
  so the agent can always read it. A destination you have made read-only is
  refused, even with `--force`, as a plain write would be (#98).
- Passing skill names together with `--all` to `install` or `uninstall` is now
  a usage error. Previously the names were silently ignored (#98).
- `docs/adapters.md` now says that symlinked parent directories of an install
  path are followed on purpose (#98).
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
  wrong for on-demand review prompts. (Steering files are now the
  `kiro-steering` legacy adapter; `kiro` installs skills.)
- Release scripts and CI read the package version through one shared helper,
  `scripts/_pyproject.py` (#114), which only looks at the `[project]` table
  (`tomllib` on Python 3.11+, a `[project]`-scoped scan on 3.10).
  `prepare_release.py` validates everything (an `X.Y.Z` version without
  leading zeros, newer than both the current version and the newest dated
  CHANGELOG section; an `[Unreleased]` section with at least one entry, not
  just `###` headings; no existing section) before it writes any file. When
  `uv lock` or plugin generation fails it restores `pyproject.toml`,
  `CHANGELOG.md`, and `uv.lock` and exits non-zero. Its "Next:" hint,
  `docs/releasing.md`, `CONTRIBUTING.md`, and the PR template now use
  `uv run --extra dev`.
- Eval fixtures are more realistic (#107): `dependency-review` now plants a
  dependency-confusion setup (`--extra-index-url` for an internal `corp-*`
  package, per pip's install docs) instead of an npm package in
  `requirements.txt`; `migration-review` gains PostgreSQL/table-size context
  (`config/database.yml`, `db/schema.rb`, a hot ~200M-row `events` table);
  `authentication-review`'s email-keyed identity becomes an intentional second
  plant, so a report can't pass on the other defect alone. Every fixture's keywords now
  describe the defect instead of echoing the planted code or naming a
  category or fix that also fits a neighbouring defect (the SAML `unverified`,
  resilience `hang`, code-smells `Extract`, dependency `public index`, and
  CI `CICD-SEC-4` keywords are gone; the GitLab fixture's stems become whole
  words), and plants the rubric clearly rates above medium (all but the
  GitLab variant's) set a `min-severity` one step below that level; the rest,
  where one step below is already the floor, need none (#106).
- Eval fixtures no longer plant their skill's own worked example (#107), so
  they test the checklist rather than recall of the example. Each of the seven
  fixtures that did now plants a different checklist item of the same skill,
  in the same small codebase: `code-smells` a `quote_total` that duplicates
  `invoice_total` (Duplicate Code, not Long Method); `iac-review` an app role
  granted `s3:*` on `*` (wildcard IAM, not `0.0.0.0/0` on port 22); `logging`
  a failed-login warning that writes the submitted username unescaped (log
  injection, not a token in the log); `migration-review` a one-step
  `rename_column` on `events` while the old release still writes the column
  (backward-incompatible change, not a non-concurrent index);
  `resilience-review` an immediate, unbacked-off retry loop around a
  shipment-creating POST with no idempotency key (two plants, not a missing
  timeout); `security-review` an owner-scoped PATCH route that passes the whole
  request body to the update as columns (mass assignment, not IDOR); and
  `ci-workflow-review` a `workflow_run` job that writes the PR run's artifact
  into `$GITHUB_ENV` (artifact poisoning, replacing both the PR-title echo and
  the `pull_request_target` head checkout) plus a third-party action pinned by
  tag. Their `expected.yaml` keywords, severity floors and sample reports are
  updated to match.

### Fixed

- Codex skills now install where Codex reads them (#99). The Codex adapter
  wrote custom prompts to `.codex/prompts/<name>.md`, but Codex only ever read
  custom prompts from `$CODEX_HOME/prompts`, never from a project, and removed
  them in 0.118.0: project installs never reached Codex, and global ones
  stopped working with 0.118.0.
  It now writes `.agents/skills/<name>/SKILL.md` (`~/.agents/skills` globally);
  the custom-prompt format is dropped rather than kept as a legacy adapter.
- Cursor rules keep their whole description. Cursor reads `.mdc` frontmatter
  one line at a time rather than as YAML, so a long description folded onto a
  second line reached Cursor cut short (7 of the 10 bundled skills). The
  `cursor-rule` adapter writes it on one line. Cursor also strips a value's
  quotes without unescaping it, so a description YAML would single-quote with
  a doubled apostrophe is written in double quotes, and one that needs
  escaping either way is refused.
- `uninstall` no longer deletes files that skilldeck didn't write or that have
  local edits. Like `install`, it refuses unless the new `uninstall --force` is
  given. It also reports per-skill errors, carries on, and exits 1 at the end.
  The error for an unstamped file says it may be an install from skilldeck
  0.3.0 or earlier. `--force` doesn't read the file, so it also removes one
  skilldeck can't read (#95).
- A symlink at an install path is no longer followed when skilldeck checks
  that path. It counts as unmanaged, so a link to a stamped file elsewhere
  can't pass for an install here. `uninstall --force` removes only the link,
  never its target (#95).
- A non-UTF-8 file, a directory, or a FIFO at an install path now counts as
  unmanaged. Before, the non-UTF-8 file and the directory crashed the command
  with a traceback, and reading the FIFO blocked it indefinitely. `install`
  and `uninstall` refuse a directory or other special file with a clear error,
  even with `--force`, and `status`/`update` no longer suggest
  `install --force` for one (#95, #96).
- `status` lists a file as an orphan only when it carries a skilldeck stamp. It
  no longer reports your own prompts, rules, or skills that share an install
  directory. Unreadable entries in those directories are skipped instead of
  crashing the command. Orphans with local edits are marked as modified
  (#96).
- `meta.yaml` values are now type-checked (#97). `name`, `description`, and
  `category` must be non-empty strings. `name` must follow the Agent Skills
  rules: at most 64 characters of `a-z`, `0-9` and `-`, with no leading,
  trailing, or doubled hyphen. `description` must be a single line of at most
  1024 characters, with no line break of any kind (including YAML escapes
  such as `\u2028`). `version` must be a YAML string of the form
  `MAJOR.MINOR.PATCH`. An unquoted `version: 1.10`, which YAML reads as the
  number `1.1`, used to be recorded as `"1.1"`; it is now rejected with a
  message to quote it. `supported-agents` must be a list of strings with no
  repeats. Invalid YAML, or a `meta.yaml` or `skill.md` that isn't UTF-8, now
  gives a clean error instead of a traceback.
- `update` no longer stops at the first failure. It reports the error for that
  skill, updates the rest, and exits 1 at the end, without also claiming
  "nothing to update" (#98).
- `status` and `provenance` no longer crash when there are no skills to list
  (#98).
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
- The eval scorer no longer passes wrong reports (#106): the report is parsed
  into individual findings (`-`, `*`, and numbered bullets), and each plant
  must be matched by its own finding naming the file and a keyword (whole
  words, case-insensitive), so a clean mention of the file, a keyword
  substring (`git` in `github`), or one finding covering two plants no longer
  counts. Only stdout is scored; a non-zero agent exit or timeout fails the
  fixture with a clear message (stderr is printed), and a fixture with plants
  but zero parsed findings fails as `output format drift?` instead of silently
  disabling the `max-findings` cap. `expected.yaml` is validated on load.
  A finding ends where its markdown list item does (a heading, a `---` rule,
  a sibling list item, or unindented text after a blank line), so a clean
  verdict on the planted file after the last finding, or after the closing
  fence of a ```` ```markdown ````-wrapped report, no longer counts; code
  fences close only on a run at least as long as the opener; a severity-led
  list item in another format fails even a clean-diff fixture as format drift
  rather than escaping the `max-findings` cap; and phrase keywords match
  across inline markdown (``no `assert` ``). The skill is installed in the
  review repo's base commit, so it is no longer an untracked change the skill
  would review.
- `ci-workflow-review` (0.2.1) no longer applies GitHub's `${{ }}` threat model
  to GitLab (#101). GitLab CI/CD variables reach the job as environment
  variables and the shell expands them once, so a quoted
  `"$CI_MERGE_REQUEST_TITLE"` is not re-parsed as shell; the skill now flags
  the real GitLab sinks (re-evaluation by anything that parses its argument as
  code — `eval`, `sh -c`, `bash -c`, `ssh`, `python -c`/`node -e`-style
  one-liners, SQL for `psql -c`; option injection, which quoting does not
  stop; unquoted expansion; values written into sourced scripts or `dotenv`
  reports), notes that merge commit titles carry the source branch name and
  merge and squash commit messages carry the MR title into protected-branch
  pipelines, and gives GitLab-native fixes instead of the GitHub-only `env:`.
  Fork-MR exposure now matches GitLab's docs (fork pipelines run in the fork
  by default; the risk is a parent-project pipeline for a fork MR reaching
  non-protected variables and runners), and
  `workflow_run` checkouts name `github.event.workflow_run.head_sha` /
  `head_branch` rather than the `pull_request` fields. GitHub and GitLab doc
  links point at their current canonical URLs. The GitLab eval fixture now
  plants a genuine `sh -c` re-evaluation of `$CI_COMMIT_TITLE` in a
  default-branch job; neither plant's keywords appear in the planted code or
  in a finding about the other plant, and a test runs the planted line with
  attacker-style variable values to prove it executes them.
- Skill citations corrected against the current standards (#102):
  `dependency-review` (0.2.3) cites OWASP Top 10:2025 A03 Software Supply
  Chain Failures instead of the retired A06:2021 and follows its wider framing
  (untrusted sources, dropped signatures, install scripts); `security-review`
  (0.3.3) files each checklist item under its ASVS 5.0 chapter with
  requirement IDs (SSRF and safe deserialization in V1, path traversal in V5,
  mass assignment in V15, cookie attributes in V3, password hashing in V11,
  V4 limited to its actual API/HTTP scope, and L3-only requirements marked so
  an L2 review does not report them without a concrete exploit path);
  `authentication-review` (0.1.1) files LDAP sign-in under V6.3; and
  `test-review` (0.2.2) now cites Google's code-review guide and *Software
  Engineering at Google*, preferring DAMP test setup and state over
  interaction checks to match them.
- `build_plugin.py`, `prepare_release.py`, `stamp_build_metadata.py`, and the
  CI build matched the first `version = "..."` line anywhere in
  `pyproject.toml`, so a `version` key in another table could be taken for the
  package version (#114).
- `check_release_consistency.py --tag` accepted any ref ending in the version
  (`refs/tags/x/v0.3.0` normalised to `0.3.0`); it now accepts only `vX.Y.Z`
  or `refs/tags/vX.Y.Z`, without leading zeros (PEP 440 would publish
  `v0.04.0` as 0.4.0), and rejects everything else with a clear error (#114).
- The release build wrote `skilldeck provenance --json` to a file nobody read;
  the new `scripts/verify_provenance.py` now asserts that the installed wheel
  reports the expected version, tag ref, commit, and skills (#114).
- Tests now read and write text files as UTF-8 explicitly (Windows defaults to
  the locale code page). Symlink tests go through one `symlink` fixture that
  skips, with the reason, only where the platform or account cannot create
  symlinks; any other error still fails the test. The tests that run GitLab
  script lines through a POSIX `sh` skip on Windows (#112).
- The declared `pyyaml>=6.0` floor could not be installed on Python 3.12 or
  newer: PyYAML 6.0 ships wheels only up to 3.11 and its source distribution
  no longer builds. The floor is now `pyyaml>=6.0.1` (#112).

- Claude Code plugin users now receive skill changes merged between releases
  (#111). Claude Code updates an installed plugin only when `plugin.json`'s
  `version` string changes, but that version only moved at release time. The
  version is now derived from the plugin content: exactly the project version
  for the content recorded in the new `claude-plugin/.skilldeck/release.json`
  when the version was bumped (by `prepare_release.py`), and
  `X.Y.(Z+1)-dev.sha256-<12 hex digits of the content digest>` for any other
  content, so every change on `main` reaches existing installs. The release
  workflow refuses a tag whose plugin is a development snapshot
  (`verify_distribution_identity.py --release-plugin`), and
  `build_plugin.py` refuses a project version older than the record.
  `check_release_consistency.py` keeps the record honest: it must equal the
  copy at its `v<version>` tag once that exists, and with `--base` (run by
  CI's `lint` job on pull requests) it fails a record change without a
  version bump and a release PR whose plugin drifted to a development version
  after `prepare_release.py`.

### Removed

- Dead `skilldeck.registry.get_skill` helper (unused, and it skipped
  `supported-agents` validation).

### Added

- `skilldeck catalog` (#77): a deterministic, schema-versioned JSON catalog
  of the bundled skills for tools (`--json`), with each skill's name,
  version, category, description, supported agents, canonical content digest
  (the one `provenance --verify` checks, recomputed from the installed files),
  source path and deprecation state. `--category` and `--agent` filter it
  without parsing text; `--schema` prints the JSON Schema, which ships in the
  package as `skilldeck/catalog.schema.json`. `docs/catalog.md` sets the
  compatibility rules: additive changes keep `schema_version` 1, breaking ones
  bump it. Releases do not attach the catalog as a separate asset; generate
  it from the verified wheel.
- Optional `deprecated` skill metadata (`since`, `reason`, optional
  `replacement`), validated by the registry; `skilldeck list` marks
  deprecated skills. No bundled skill is deprecated.

- `frontend-security-review` skill (0.1.0) (#105) — reviews browser-side
  changes (React, Vue, Angular, Svelte, plain JavaScript and HTML templates,
  CSP and header config): framework escape hatches (`dangerouslySetInnerHTML`,
  `v-html`, `bypassSecurityTrust*`, `{@html}`) and DOM XSS sinks (`innerHTML`,
  `insertAdjacentHTML`, `document.write`, string `eval`/`setTimeout`,
  `javascript:` URLs), weakened CSP (`'unsafe-inline'`, `'unsafe-eval'`,
  wildcard sources, missing `object-src`/`base-uri`, report-only), missing
  `frame-ancestors`, `message` listeners without an origin check and
  `postMessage` to `"*"`, sensitive data in web storage, secrets inlined into
  client bundles through `NEXT_PUBLIC_`/`VITE_` variables, third-party scripts
  without SRI (a mutable CDN URL is a mutable pin), and client-side open
  redirects. Classified by OWASP ASVS 5.0 chapter (V3 Web Frontend Security,
  with V1, V13 and V14), with patterns from the OWASP XSS, DOM-based XSS, CSP,
  HTML5 Security, Clickjacking and Third-Party JavaScript cheat sheets and the
  React, Vue, Angular, Svelte, Next.js, Vite and MDN docs and the React
  changelog. Registered in `docs/finding-output.md` as the owner of
  browser-side V3 (server-side CORS and CSRF checks stay with
  `security-review`; cookies and session or OAuth tokens in browser storage
  with `authentication-review`), of live credentials shipped in client code,
  and of mutable pins in page `<script>`/`<link>` tags; `security-review`
  (0.5.1) hands it browser-side code and page headers among its companion
  skills. Ships with a planted eval fixture (a member-written bio rendered
  through `dangerouslySetInnerHTML`, and a help-widget `message` listener that
  navigates wherever any sender asks) and a clean one (the same change with
  DOMPurify and a sender- and URL-checked listener).
- `llm-integration-review` skill (0.1.0) (#105) — reviews changes that
  integrate LLMs or AI agents: prompt injection through untrusted context
  (retrieved documents, tickets, tool and MCP results), model output reaching
  a shell, SQL, `eval`, HTML, file paths or fetched URLs, excessive agency
  (open-ended or over-privileged tools, no human approval before side
  effects), secrets in prompts and hidden context, prompts and PII in logs,
  per-tenant scoping of RAG retrieval, MCP configuration (unvetted servers,
  tool poisoning, token passthrough, confused deputy, wildcard scopes, local
  server launch), model supply chain (mutable model references,
  `trust_remote_code`, pickle loading), and unbounded consumption (no token,
  step or cost limits). Classified against the OWASP Top 10 for LLM
  Applications 2026 (`LLM01:2026`–`LLM10:2026`), with patterns from the MCP
  Security Best Practices and tools specification (2026-07-28) and Hugging
  Face's custom-model loading guidance. Ships with a planted eval fixture (a
  support-bot endpoint where the customer-written ticket steers a shell tool
  with no allow-list or confirmation, inside an uncapped tool-calling loop)
  and a clean one (allow-listed tag suggestions a human applies, with an
  output-token cap). A citation test now rejects `LLMxx:2025` IDs, since the
  2026 edition renumbered the entries.
- `privacy-review` skill (0.1.0) (#105) — reviews changes that handle
  personal data: over-collection and over-broad responses (whole records or
  `SELECT *` rows where a few fields suffice, precision beyond need, upload
  metadata), personal data sent to analytics, ad, session-replay or
  error-tracking tools without a consent check (including Sentry's
  `send_default_pii` and `data_collection` defaults), fingerprinting and
  pre-consent identifiers, new personal-data stores with no retention or
  deletion path, soft deletes that leave PII readable, export and deletion
  code that misses new tables, sensitive categories (health, precise
  location, government IDs, biometrics) stored in plaintext, and PII in URLs,
  shared caches, and browser storage. Grounded in OWASP ASVS 5.0 V14 (with
  3.4.5 and 15.3.1), the OWASP Top 10 Privacy Risks, the OWASP User Privacy
  Protection Cheat Sheet, the CNIL GDPR Developer Guide, and the W3C
  fingerprinting guidance; it stays technical and gives no legal advice.
  Registered in `docs/finding-output.md` as the owner of personal-data
  handling (V14, and 15.3.1 when the over-returned fields are personal data)
  instead of `security-review`; PII in logs stays with `logging` and PII in
  prompts with `llm-integration-review`. `security-review`'s own companion
  list does not name `privacy-review` yet. Ships with a planted eval
  fixture (a member directory returning the whole user row, national ID
  included, and a page-view hook sending email and phone coordinates to
  Segment with no consent check) and a clean one (an explicit public-field
  allow-list and a consent-gated hook keyed on a random analytics ID that
  sends only the route template).
- `skilldeck migrate --agent <agent>|all [--scope ...] [--force]` moves skills
  installed in an agent's old format (Codex custom prompts, Copilot prompt
  files, Cursor rules, Kiro steering files) to its `SKILL.md` folder: it
  installs the native skill, then removes the old file. Global Codex prompts
  and Kiro steering files are found under `~/.codex/prompts` and
  `~/.kiro/steering`, where skilldeck wrote them whatever `CODEX_HOME` or
  `KIRO_HOME` said, and in `$KIRO_HOME/steering`. The #95 rules apply to the
  old file: one with local edits is left in place and reported unless
  `--force` is given, and so, for Codex and Kiro, is one without a stamp
  (such as an install from skilldeck 0.3.0 or earlier) or a symlink; a
  directory is never removed. skilldeck always stamped Copilot prompt files
  and Cursor rules, so an unstamped one is the user's own and is never
  touched. `--force` never reaches the new location: a locally modified
  `SKILL.md` there is kept as it is, and a file skilldeck didn't write there
  stops the move. Running it again is a no-op. `status` and `update` print a
  one-line hint for each agent with old installs, counting unstamped files
  separately (#100).
- Legacy adapters for agent versions without skills support, selected by
  name and applied to every skill that supports their agent, so no
  `meta.yaml` changes: `copilot-prompt` (`.github/prompts/<name>.prompt.md`,
  project only, now with `agent: agent` so the prompt runs in agent mode and
  can use tools), `cursor-rule` (`.cursor/rules/<name>.mdc`, project only) and
  `kiro-steering` (`.kiro/steering/<name>.md`, both scopes). `supported-agents`
  still accepts only the five agent names (#100).
- Release trust chain (#76): exact tag/commit metadata in wheel and source
  distribution, a shared canonical content manifest for Python and the Claude
  plugin, `skilldeck provenance`, archive-safe cross-distribution verification,
  a runtime-only SPDX 2.3 SBOM, exact SHA-256 checksums, GitHub build/SBOM
  attestations, PyPI PEP 740 verification, and post-publication channel and
  tamper checks. Consumer and operator verification procedures are documented.
- `docs/releasing.md` documenting the versioning and release procedure, plus
  `scripts/check_release_consistency.py` — a stdlib guard that asserts the
  `pyproject` version, the newest dated CHANGELOG section, and (on a tag push) the
  release tag all agree. Wired into CI (`lint` job and `pytest`) and the release
  workflow (before publish), so version/CHANGELOG/tag drift fails fast.
- CI coverage (#112): tests also run on Windows and macOS (Python 3.14) and
  against the lowest dependency versions the declared ranges allow
  (`uv run --resolution lowest-direct`, Python 3.10 and 3.14); a pinned
  zizmor audits `.github/` (workflows and Dependabot config); and the CI
  build installs the built sdist into a clean venv and smoke-tests
  `skilldeck list` and `skilldeck provenance --json` against it.
- Eval runner options and fields (#106, #107): `--repeat N` reports a pass rate
  per fixture; `--adapter NAME` installs the skill through any skilldeck
  adapter, and the prompt names the installed path instead of hard-coding
  `.claude/skills`; per-plant `min-severity` and `locators`; `--skill` also
  selects a skill's variant fixtures. Clean-diff fixtures (`plants: []`) are
  now allowed, with `security-review-clean` (parameterized, owner-scoped query)
  and `resilience-review-clean` (timeout plus bounded, jittered retry on an
  idempotent GET that ignores an uncapped `Retry-After`) measuring false
  positives. A structural test rejects plant keywords that appear verbatim in
  the planted file, and per-fixture sample reports check that a correct report
  passes and a finding about a neighbouring defect satisfies no plant.
- `skilldeck provenance --verify` re-hashes each installed skill's `meta.yaml`
  and `skill.md` and exits 1, naming the skill, when one no longer matches its
  recorded canonical digest, is missing, or has unexpected files beside it.
  Plain `provenance` reports only the identities embedded at build time; the
  docs now say so. CI and the release workflow run the installed wheel and
  sdist with `--verify` (#109).

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
