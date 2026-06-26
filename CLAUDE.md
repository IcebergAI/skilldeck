# Skillful

## Overview
Skillful is a collection of skills for coding assistants to use mostly for security and code review purposes. The skills are agent agnostic and come with an install script that provides options for project local or global install.

## Stack

### Install script
- Python (>=3.9)
- Click (CLI)
- PyYAML (skill metadata)
- Packaged with hatchling; exposes the `skilldeck` console script
- Tooling: `uv` for venv/install/test (no system pip available)
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
 