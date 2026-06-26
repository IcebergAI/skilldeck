# Adapters

An adapter translates a canonical skill into the file format and location a
specific agent expects. They live in `src/skilldeck/adapters/` and are registered
in `adapters/__init__.py` (`ADAPTERS`).

## Install locations

`--scope project` resolves paths against the current directory; `--scope global`
resolves against `$HOME`. The relative path below is the same in both cases.

| Agent  | Relative path                          | Format                         |
|--------|----------------------------------------|--------------------------------|
| claude | `.claude/skills/<name>/SKILL.md`       | body + YAML frontmatter        |
| codex  | `.codex/prompts/<name>.md`             | body as-is                     |
| kiro   | `.kiro/steering/<name>.md`             | body as-is                     |

> The Codex and Kiro paths follow each tool's documented conventions; verify
> against your installed version and adjust the adapter if they differ.

## Adding a new agent

1. Create `src/skilldeck/adapters/<agent>.py` with a subclass of `Adapter`:
   - set `name`
   - implement `relative_path(skill)` and `render(skill)`
2. Register the instance in `ADAPTERS` in `adapters/__init__.py`.
3. Add the agent name to the `supported-agents` list of any skill it should apply
   to.

The base class handles `install`/`uninstall`, directory creation, and scope
resolution, so an adapter only describes *where* the file goes and *what* it
contains.
