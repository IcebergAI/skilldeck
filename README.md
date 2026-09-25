<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/IcebergAI/skilldeck/main/docs/assets/skilldeck-logo-horizontal.svg">
    <img alt="Skilldeck" src="https://raw.githubusercontent.com/IcebergAI/skilldeck/main/docs/assets/skilldeck-logo-horizontal-onlight.svg" width="340">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/IcebergAI/skilldeck/actions/workflows/ci.yml"><img src="https://github.com/IcebergAI/skilldeck/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/IcebergAI/skilldeck"><img src="https://img.shields.io/badge/python-3.10%E2%80%933.14-blue" alt="Python"></a>
  <a href="https://github.com/IcebergAI/skilldeck/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="License: MIT"></a>
</p>

A collection of skills for coding assistants, focused on security and code review.
Skills are authored once in an agent-neutral format and installed into whichever
assistant you use.

## Supported agents

- Claude (Claude Code)
- OpenAI Codex (0.95.0 or later)
- GitHub Copilot (VS Code agent mode, Copilot CLI, the cloud agent)
- Cursor
- Kiro

Every agent gets the same [Agent Skills](https://agentskills.io/specification)
`SKILL.md` folder, in the project or in your home directory. For agent
versions too old for skills, the earlier formats remain available as the
`copilot-prompt`, `cursor-rule` and `kiro-steering` adapters. See
[docs/adapters.md](docs/adapters.md) for each agent's locations and minimum
version, and the [compatibility matrix](docs/compatibility.md) for how each
adapter is invoked, which agent versions it was checked against, and how
well.

## Claude Code: install as a plugin (no Python needed)

Claude Code users can skip the CLI entirely — this repo is a plugin
marketplace. In Claude Code:

```
/plugin marketplace add IcebergAI/skilldeck
/plugin install skilldeck@skilldeck
```

The skills then appear namespaced (e.g. `/skilldeck:security-review`) and
update via `/plugin update`. The plugin follows this repo's `main` branch:
between releases every change to its content ships under a new development
version (such as `0.3.1-dev.sha256-8bc06884da4f`), so `/plugin update` picks
it up; Claude Code keeps auto-update off for third-party marketplaces unless
you turn it on. Use the CLI below if you want per-skill selection, other
agents, or plain files in your project.

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
uvx --from git+https://github.com/IcebergAI/skilldeck skilldeck install security-review --agent claude
```

Or put `skilldeck` on your PATH:

```bash
uv tool install git+https://github.com/IcebergAI/skilldeck
# or: pipx install git+https://github.com/IcebergAI/skilldeck
```

### From a local clone

Useful for authoring skills or trying local changes:

```bash
git clone https://github.com/IcebergAI/skilldeck && cd skilldeck
uv run --extra dev skilldeck list      # run in place, no install
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
`uvx --from git+https://github.com/IcebergAI/skilldeck ` — e.g.
`uvx --from git+https://github.com/IcebergAI/skilldeck skilldeck list`.

```bash
# See what's available
skilldeck list

# Preview a skill before installing: its instructions, then its source,
# digest and declared capabilities, then what an install would write
skilldeck show security-review
skilldeck show security-review --summary
skilldeck install security-review --agent claude --dry-run

# Install a skill for Claude into the current project
skilldeck install security-review --agent claude

# Install for several agents at once (repeat --agent, or use 'all')
skilldeck install security-review --agent claude --agent codex
skilldeck install --all --agent all

# Install every compatible skill globally for Codex
skilldeck install --all --agent codex --scope global

# Use an older format for an agent version without skills support
skilldeck install security-review --agent copilot-prompt

# Move installs made in the older formats to the skills folders
skilldeck migrate --agent all

# Remove a skill
skilldeck uninstall security-review --agent claude

# See what's installed and whether it's current (repeat --agent, or use 'all')
skilldeck status --agent claude
skilldeck status --agent all

# Refresh installed skills after upgrading skilldeck
skilldeck update --agent claude

# Show the source identity and skill digests recorded at build time (claims only)
skilldeck provenance
skilldeck provenance --json

# Re-hash the installed skills and fail if any differ from those build-time digests
skilldeck provenance --verify

# Machine-readable, schema-versioned skill catalog for tools (filters optional)
skilldeck catalog --json
skilldeck catalog --json --category security --agent claude

# Author a skill: scaffold it, then check it against every rule, offline
skilldeck new my-review --category security --dir skills
skilldeck validate --skills-dir skills my-review
```

`skilldeck catalog --json` is a stable contract for tools; see
[docs/catalog.md](docs/catalog.md) for its schema and compatibility rules.

Every skill declares its capabilities: which files it reads or edits, the
commands it may ask your agent to run, what it contacts over the network and
why, and any credentials, agent tools or new files it needs. Anything not
declared is not requested. `show --summary` and `install --dry-run` print the
declaration before you install. A skill that asks for more than a read-only
review (reading files and read-only git commands) also carries it in its
installed `SKILL.md`, as a "Declared capabilities" section telling your agent
what the skill asks of it. It is a declaration for review, not a sandbox:
skilldeck can't enforce it inside your agent, so review what a skill asks for
(see [Capabilities](docs/authoring-skills.md#capabilities)).

Installed files carry a `skilldeck` stamp recording the skill version, so
`status` can tell current, stale, and locally modified installs apart. Files you
have edited, or that skilldeck didn't write, are never overwritten or deleted
unless you pass `--force` to `install` or `uninstall`. `update --force` also
refreshes edited installs, but it never touches files that skilldeck didn't
write. skilldeck never writes through a symlink at an install path.
`uninstall --force` removes the link itself and leaves its target alone. See
[docs/adapters.md](docs/adapters.md#stamps-what-skilldeck-will-overwrite-or-delete)
for the details.

Upgrading: Codex and Kiro skills now install as `SKILL.md` folders instead of
the custom prompts and steering files that skilldeck 0.3.0 and earlier wrote.
(Codex never read custom prompts from a project, and has since removed them
altogether.) If you used a development build with the Copilot and Cursor
adapters, their prompt files and rules become skills too. Run
`skilldeck migrate --agent all` (and again with `--scope global` for global
installs) to replace the old files with skills; `status` prints a hint while
old files remain. skilldeck 0.3.0 and earlier didn't stamp what they
installed, so skilldeck treats their files as ones it didn't write: check the
files the hint counts, then run `migrate` with `--force`, which never
overwrites a `SKILL.md` you have edited. For Claude skills from those
versions, run `install --force` once to replace them with stamped copies (or
`uninstall --force` to remove them), after which `update` and `uninstall`
work without `--force`. See
[Migrating from the old formats](docs/adapters.md#migrating-from-the-old-formats).

`--agent all` means every agent's native skills folder; the older formats are
used only when you name them.

`--scope project` (default) writes into the current directory, so run it from
your repository root. `--scope global` writes into your home directory, or
into the directory named by `CLAUDE_CONFIG_DIR`, `COPILOT_HOME` or `KIRO_HOME`
when you have set one. Install each skill once per agent, at one scope: see
[Where each agent looks, and duplicates](docs/adapters.md#where-each-agent-looks-and-duplicates).

## Release trust

Tagged releases publish one wheel, one source distribution, an SPDX 2.3 runtime
SBOM, and `SHA256SUMS`. GitHub build/SBOM attestations and PyPI's Trusted
Publishing attestation bind those bytes to the exact tag commit. The release
workflow downloads both channels again and rejects checksum, provenance, SBOM,
content-manifest, or tamper-test failures before it succeeds.

See [Verifying a Skilldeck release](docs/verifying-releases.md) for the complete
consumer procedure. These commands become actionable with the first published
release; the package remains unpublished today.

## Authoring skills

Each skill is a directory under `src/skilldeck/skills/` containing a `meta.yaml`
(including its capability declaration) and a `skill.md`, and nothing else.
Start one with `skilldeck new` and check it with `skilldeck validate`, which
names the file, rule and fix for every problem; in your own repository, pass
`--dir` / `--skills-dir` to keep organization skills there. See
[docs/authoring-skills.md](docs/authoring-skills.md), including the review path
for official and organization skills, and follow the
[contributor guide](CONTRIBUTING.md) for setup.

## Changelog and support

Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).
[docs/lifecycle.md](docs/lifecycle.md) says what each kind of version bump
means, how long deprecated skills, agents and formats stay supported (a
deprecation ships in a release at least 90 days before the removal), and
what happens to skills you have already installed when one is removed.
