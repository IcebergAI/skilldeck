# Skilldeck

## Overview
Skilldeck is a collection of skills for coding assistants to use mostly for security and code review purposes. The skills are agent agnostic and come with an install script that provides options for project local or global install.

## Stack

### Install script
- Python (>=3.10)
- Click (CLI)
- PyYAML (skill metadata)
- Packaged with hatchling; exposes the `skilldeck` console script
- Tooling: `uv` for venv/install/test (no system pip available); `ruff` for
  lint+format and `mypy` (strict on `src`) for types. Run before pushing:
  `uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy && uv run --extra dev pytest`
  (always pass `--extra dev` — bare `uv run` re-syncs the venv without extras
  and uninstalls the dev tools)
- CI (`.github/workflows/ci.yml`) runs lint, types, a 3.10–3.14 pytest matrix,
  Windows/macOS test legs, a lowest-direct dependency-floor job (3.10 and 3.14),
  zizmor on `.github/`, and a build (plus a build with the hatchling floor) +
  sdist smoke test on every PR; all CI/release `uv run`/`uv sync` calls pass
  `--locked` (except the floor job). Tagged `v*` releases publish to PyPI via
  Trusted Publishing (`release.yml`), gated on the tag commit being on `main`
  and passing the checks (a guard against mis-tagging; the tag ruleset and
  `pypi` environment reviewer in repo settings are the real controls)
- Tests run on Windows too: pass `encoding="utf-8"` to every text read/write
  and create symlinks via the `symlink` fixture (`tests/conftest.py`)
- Scripts read the package version only via `scripts/_pyproject.py`
  (`[project].version`); don't add another parser
- Distribution: it's a CLI app, not a library — recommend isolated installs
  (`uvx skilldeck`, `uv tool install`, `pipx`); `pip install` is a fallback only.
  Don't document bare `pip install` as the primary path.

## Supported agents/harnesses
All five get the same Agent Skills `SKILL.md` folder at project and global
scope (locations, env overrides and minimum versions: `docs/adapters.md`):
- Claude (also installable as a Claude Code plugin marketplace)
- OpenAI Codex
- GitHub Copilot
- Cursor
- Kiro

Opt-in legacy adapters keep the pre-skills formats for older agent versions:
`copilot-prompt`, `cursor-rule`, `kiro-steering` (selected only by name, never
by `--agent all`); `skilldeck migrate` moves old-format installs to `SKILL.md`.

## Layout
- `src/skilldeck/skills/<name>/` — canonical, agent-neutral skills (`meta.yaml` +
  `skill.md`); inside the package so they're bundled into the wheel
- `src/skilldeck/` — the installer package
  - `cli.py` — `skilldeck list/show/install/uninstall/status/update/migrate`,
    `provenance` and `catalog`
  - `registry.py` — discovers and validates skills, including the optional
    `deprecated` metadata, and the bundle rules: a skill directory is exactly
    regular `meta.yaml` + `skill.md` (no scripts, assets or symlinks), and
    `skill.md` links only to the web or its own headings
  - `capabilities.py` — the versioned `capabilities` declaration every
    `meta.yaml` carries (files, commands, network, credentials, tools,
    artifacts), its validation, the `## Declared capabilities` notice
    adapters append for skills that ask for more than reading files, and the
    summary `show --summary` / `install --dry-run` print
  - `catalog.py` + `catalog.schema.json` — the public, schema-versioned
    `skilldeck catalog --json` contract (the schema ships in the wheel);
    change it only per the compatibility rules in `docs/catalog.md` (bump
    `CATALOG_SCHEMA_VERSION` for breaking changes only)
  - `stamp.py` — install stamps (version + content hash on installed files)
  - `targets.py` — install scope, project base dir, and `UserDir` (an agent's
    user-level folder, with its env-var override)
  - `adapters/` — per-agent translation: native `SKILL.md` adapters (claude,
    codex, copilot, cursor, kiro) share `SkillMdAdapter` and only declare
    their `project_dir`/`global_dir`; `legacy.py` holds the opt-in older
    formats and the migration sources. Add an agent by subclassing
    `SkillMdAdapter` (or `Adapter`) and registering it in `ADAPTERS` in
    `adapters/__init__.py`; `ADAPTERS` keys are the valid `supported-agents`
    names
- `tests/` — pytest suite (`uv run --extra dev pytest`)
- `evals/` — golden-diff skill evals (`python evals/run_evals.py`, with
  `--repeat N` for pass rates and `--adapter` for non-Claude agents): fixtures
  with planted defects (or `plants: []` clean-diff fixtures for false
  positives), scored against a real agent; manual (paid API). CI runs no agent:
  it validates fixture structure (keywords must describe the defect, never
  echo the planted code) and each fixture's `SAMPLE_REPORTS` in
  `tests/test_eval_fixtures.py`, and unit-tests the scorer
  (`tests/test_eval_scoring.py`). See `evals/README.md`. New/changed skills
  should be run through them.
- `docs/` — `authoring-skills.md`, `adapters.md`, `catalog.md`, `compatibility.md`
  (the public agent compatibility matrix), `releasing.md`
- `tests/fixtures/adapter-contracts/` — each adapter's exact rendered file,
  paths and env-override behaviour for one synthetic skill; checked byte for
  byte by `tests/test_adapter_contracts.py`
- `.claude-plugin/marketplace.json` + `claude-plugin/` — the Claude Code plugin
  marketplace tree, **generated** by `scripts/build_plugin.py` from the
  canonical skills; regenerate after changing skills or the project version (a
  pytest freshness guard enforces this), never edit by hand. Marketplace users
  get `main`, and Claude Code updates a plugin only when `plugin.json`'s
  `version` string changes, so that version is derived from the plugin
  content: exactly the project version for the content recorded in
  `claude-plugin/.skilldeck/release.json` when the version was bumped, else
  `X.Y.(Z+1)-dev.sha256-<12 hex>` (see `docs/releasing.md`). Never restore or
  edit that record outside an unmerged release PR:
  `scripts/check_release_consistency.py` fails a record change without a
  version bump, or one that differs from its release tag's copy
- `src/skilldeck/_content_manifest.json` +
  `claude-plugin/.skilldeck/content-manifest.json` — identical generated
  canonical and rendered-skill identities; regenerated with the plugin tree,
  never edited by hand
- `src/skilldeck/_build_metadata.json` — development placeholder; only
  `scripts/stamp_build_metadata.py` may add an exact release tag/full commit in
  the authorized tag workflow

## Conventions
- Skills are authored once in `src/skilldeck/skills/`; never hand-edit per-agent
  output.
- A skill's `meta.yaml` `name` must match its directory name; all metadata fields
  (except `deprecated`) are required and validated by the registry.
- Every skill declares `capabilities` (schema 1, every key spelled out, `[]`
  or `none` when unused) that match what `skill.md` actually asks the agent
  to do; update it with the body (`tests/test_skill_structure.py` checks
  declared commands against the body both ways). Undeclared means not
  requested; it is a declaration for review, never presented as
  enforcement. See `docs/authoring-skills.md#capabilities`.
- Any change to an adapter's output format, paths or env handling must update
  its contract fixtures, the `adapter-contract` digest and matrix rows in
  `docs/compatibility.md`, and CHANGELOG. The contract tests enforce the
  fixtures, the digest line, a digest mention in CHANGELOG, and the matrix's
  path/"Moved by"/scope-error text. Status, minimum versions, dates and notes
  are maintained by hand (see `docs/compatibility.md#contract-tests`). Only
  state vendor behaviour a primary source confirms; mark the rest
  *unverified*.
- New skills follow the structural template (enforced by
  `tests/test_skill_structure.py`), ground their checklists in **fetched**
  authoritative sources (OWASP/CIS/vendor docs) cited in the skill body, and
  land with a golden-diff eval fixture under `evals/fixtures/` (ideally also a
  `-clean` one).
- Review skills report in the shared shape of `docs/finding-output.md` and
  inline its one-paragraph severity rubric word for word in `## Output`
  (`tests/test_skill_structure.py` compares them); change the rubric in the doc
  and every skill together. Respect its "Which skill owns what" table: a
  defect is reported once, by its owning skill.

## Shipping
- PRs squash-merge to main: `gh pr merge <n> --squash --delete-branch` after CI
  passes (~1 min). Branch protection requires the branch be up to date with
  main — on a rejected merge, `gh pr update-branch <n>`, re-watch checks, merge.

## Maintenance
- Keep this file up to date with relevant info for agents contributing to the project
- Maintain a README.md for users installing skills
- Record notable changes in CHANGELOG.md (Keep a Changelog format) under
  `[Unreleased]`; bump a skill's `meta.yaml` `version` when its content changes
- Releasing and project versioning: see `docs/releasing.md`. The project version
  (`pyproject.toml`), the newest dated CHANGELOG section, and the release tag must
  stay in sync — `scripts/check_release_consistency.py` enforces this in CI and
  `pytest`. A dated CHANGELOG section without a matching `v*` tag is prepared, not
  published.
- Release CI must build once, verify wheel/sdist/plugin identity (against the
  tagged commit's files), produce a runtime-only SPDX SBOM and exact
  checksums, attest those bytes, then publish the same bundle. The build job
  hands the bundle digests to later jobs as a job output; each job checks its
  download against them before use. Keep build, attest, PyPI, and
  GitHub-release permissions in separate jobs, keep the PyPI byte readback
  ahead of the GitHub release, and preserve the post-publication
  readback/tamper gate (which must accept only gh's "no attestations found"
  rejection).
