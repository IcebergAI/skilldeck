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
  `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
- CI (`.github/workflows/ci.yml`) runs lint, types, and a 3.10–3.14 pytest matrix
  on every PR; tagged `v*` releases publish to PyPI via Trusted Publishing
  (`release.yml`)
- Distribution: it's a CLI app, not a library — recommend isolated installs
  (`uvx skilldeck`, `uv tool install`, `pipx`); `pip install` is a fallback only.
  Don't document bare `pip install` as the primary path.

## Supported agents/harnesses
- Claude
- OpenAI Codex
- Kiro

## Layout
- `src/skilldeck/skills/<name>/` — canonical, agent-neutral skills (`meta.yaml` +
  `skill.md`); inside the package so they're bundled into the wheel
- `src/skilldeck/` — the installer package
  - `cli.py` — `skilldeck list/install/uninstall`
  - `registry.py` — discovers and validates skills
  - `targets.py` — install scope (project vs global base dir)
  - `adapters/` — per-agent translation (claude, codex, kiro); add an agent by
    subclassing `Adapter` and registering it in `adapters/__init__.py`
- `tests/` — pytest suite (`uv run pytest`)
- `docs/` — `authoring-skills.md`, `adapters.md`

## Conventions
- Skills are authored once in `src/skilldeck/skills/`; never hand-edit per-agent
  output.
- A skill's `meta.yaml` `name` must match its directory name; all metadata fields
  are required and validated by the registry.


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
 