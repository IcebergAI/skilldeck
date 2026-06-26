# Skillful

A collection of skills for coding assistants, focused on security and code review.
Skills are authored once in an agent-neutral format and installed into whichever
assistant you use.

## Supported agents

- Claude (Claude Code)
- OpenAI Codex
- Kiro

## Running skillful

`skillful` is a CLI you run occasionally to copy skills into your assistant — not
a library you import. So install it in isolation (or don't install it at all)
rather than into your global Python environment.

### No install (recommended)

Run it directly with [uv](https://docs.astral.sh/uv/); nothing is left behind:

```bash
uvx skillful install security-review --agent claude
```

`pipx run skillful ...` works the same way if you use pipx instead of uv.

### Persistent command

If you'd rather have `skillful` on your PATH:

```bash
uv tool install skillful      # or: pipx install skillful
```

### From a clone (for authoring skills)

```bash
git clone <repo> && cd skillful
uv run skillful list
```

> `pip install skillful` also works, but installs into the active environment —
> prefer one of the isolated options above.

## Usage

The examples below assume an installed `skillful`; prefix with `uvx ` (or
`pipx run `) to run without installing.

```bash
# See what's available
skillful list

# Install a skill for Claude into the current project
skillful install security-review --agent claude

# Install every compatible skill globally for Codex
skillful install --all --agent codex --scope global

# Remove a skill
skillful uninstall security-review --agent claude
```

`--scope project` (default) writes into the current directory; `--scope global`
writes into your home directory. Where exactly each agent looks is documented in
[docs/adapters.md](docs/adapters.md).

## Authoring skills

Each skill is a directory under `src/skillful/skills/` containing a `meta.yaml`
and a `skill.md`. See [docs/authoring-skills.md](docs/authoring-skills.md).

## Changelog

Notable changes are recorded in [CHANGELOG.md](CHANGELOG.md).
