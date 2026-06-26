# Skilldeck

[![CI](https://github.com/TheSlopBucket/skilldeck/actions/workflows/ci.yml/badge.svg)](https://github.com/TheSlopBucket/skilldeck/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%E2%80%933.13-blue)](https://github.com/TheSlopBucket/skilldeck)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

A collection of skills for coding assistants, focused on security and code review.
Skills are authored once in an agent-neutral format and installed into whichever
assistant you use.

## Supported agents

- Claude (Claude Code)
- OpenAI Codex
- Kiro

## Running skilldeck

`skilldeck` is a CLI you run occasionally to copy skills into your assistant — not
a library you import. So install it in isolation (or don't install it at all)
rather than into your global Python environment.

### No install (recommended)

Run it directly with [uv](https://docs.astral.sh/uv/); nothing is left behind:

```bash
uvx skilldeck install security-review --agent claude
```

`pipx run skilldeck ...` works the same way if you use pipx instead of uv.

### Persistent command

If you'd rather have `skilldeck` on your PATH:

```bash
uv tool install skilldeck      # or: pipx install skilldeck
```

### From a clone (for authoring skills)

```bash
git clone <repo> && cd skilldeck
uv run skilldeck list
```

> `pip install skilldeck` also works, but installs into the active environment —
> prefer one of the isolated options above.

## Usage

The examples below assume an installed `skilldeck`; prefix with `uvx ` (or
`pipx run `) to run without installing.

```bash
# See what's available
skilldeck list

# Install a skill for Claude into the current project
skilldeck install security-review --agent claude

# Install every compatible skill globally for Codex
skilldeck install --all --agent codex --scope global

# Remove a skill
skilldeck uninstall security-review --agent claude
```

`--scope project` (default) writes into the current directory; `--scope global`
writes into your home directory. Where exactly each agent looks is documented in
[docs/adapters.md](docs/adapters.md).

## Authoring skills

Each skill is a directory under `src/skilldeck/skills/` containing a `meta.yaml`
and a `skill.md`. See [docs/authoring-skills.md](docs/authoring-skills.md).

## Changelog

Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).
