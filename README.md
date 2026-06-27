<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TheSlopBucket/skilldeck/main/docs/assets/skilldeck-logo-horizontal.svg">
    <img alt="Skilldeck" src="https://raw.githubusercontent.com/TheSlopBucket/skilldeck/main/docs/assets/skilldeck-logo-horizontal-onlight.svg" width="340">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/TheSlopBucket/skilldeck/actions/workflows/ci.yml"><img src="https://github.com/TheSlopBucket/skilldeck/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/TheSlopBucket/skilldeck"><img src="https://img.shields.io/badge/python-3.10%E2%80%933.14-blue" alt="Python"></a>
  <a href="https://github.com/TheSlopBucket/skilldeck/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License: MIT"></a>
</p>

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

> [!NOTE]
> **Not on PyPI yet.** Until the first release is published, the `skilldeck`
> package name does not resolve, so the direct commands in the
> [From PyPI](#from-pypi-once-published) section below (`uvx skilldeck`,
> `pip install skilldeck`, …) **do not work yet**. Use the **git** or **local
> clone** methods for now.

### From git

Run it without installing, straight from the repo (needs
[uv](https://docs.astral.sh/uv/)):

```bash
uvx --from git+https://github.com/TheSlopBucket/skilldeck skilldeck install security-review --agent claude
```

Or put `skilldeck` on your PATH:

```bash
uv tool install git+https://github.com/TheSlopBucket/skilldeck
# or: pipx install git+https://github.com/TheSlopBucket/skilldeck
```

### From a local clone

Useful for authoring skills or trying local changes:

```bash
git clone https://github.com/TheSlopBucket/skilldeck && cd skilldeck
uv run skilldeck list                  # run in place, no install
uv tool install .                      # or: pipx install .  — put it on PATH
```

### From PyPI (once published)

After the first release these isolated runs will work:

```bash
uvx skilldeck install security-review --agent claude   # no install, nothing left behind
pipx run skilldeck ...                                 # same, via pipx
uv tool install skilldeck                              # or: pipx install skilldeck — persistent
```

> `pip install skilldeck` will also work, but installs into the active
> environment — prefer one of the isolated options above.

## Usage

The examples below assume `skilldeck` is on your PATH (see
[Running skilldeck](#running-skilldeck)). To run without installing while the
package is unpublished, prefix each command with
`uvx --from git+https://github.com/TheSlopBucket/skilldeck ` — e.g.
`uvx --from git+https://github.com/TheSlopBucket/skilldeck skilldeck list`.

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
