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
- CI (`.github/workflows/ci.yml`) runs lint, types, and a 3.10–3.14 pytest matrix
  on every PR; tagged `v*` releases publish to PyPI via Trusted Publishing
  (`release.yml`)
- Distribution: it's a CLI app, not a library — recommend isolated installs
  (`uvx skilldeck`, `uv tool install`, `pipx`); `pip install` is a fallback only.
  Don't document bare `pip install` as the primary path.

## Supported agents/harnesses
- Claude (also installable as a Claude Code plugin marketplace)
- OpenAI Codex
- GitHub Copilot (project scope only)
- Cursor (project scope only)
- Kiro

## Layout
- `src/skilldeck/skills/<name>/` — canonical, agent-neutral skills (`meta.yaml` +
  `skill.md`); inside the package so they're bundled into the wheel
- `src/skilldeck/` — the installer package
  - `cli.py` — `skilldeck list/show/install/uninstall/status/update`
  - `registry.py` — discovers and validates skills
  - `stamp.py` — install stamps (version + content hash on installed files)
  - `targets.py` — install scope (project vs global base dir)
  - `adapters/` — per-agent translation (claude, codex, copilot, cursor, kiro);
    add an agent by subclassing `Adapter` and registering it in
    `adapters/__init__.py`
- `tests/` — pytest suite (`uv run --extra dev pytest`)
- `evals/` — golden-diff skill evals (`python evals/run_evals.py`): fixtures
  with planted defects, scored against a real agent; manual (paid API), CI only
  validates fixture structure. New/changed skills should be run through them.
- `docs/` — `authoring-skills.md`, `adapters.md`, `releasing.md`
- `.claude-plugin/marketplace.json` + `claude-plugin/` — the Claude Code plugin
  marketplace tree, **generated** by `scripts/build_plugin.py` from the
  canonical skills; regenerate after changing skills or the project version (a
  pytest freshness guard enforces this), never edit by hand

## Conventions
- Skills are authored once in `src/skilldeck/skills/`; never hand-edit per-agent
  output.
- A skill's `meta.yaml` `name` must match its directory name; all metadata fields
  are required and validated by the registry.
- New skills follow the structural template (enforced by
  `tests/test_skill_structure.py`), ground their checklists in **fetched**
  authoritative sources (OWASP/CIS/vendor docs) cited in the skill body, and
  land with a golden-diff eval fixture under `evals/fixtures/`.

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
 