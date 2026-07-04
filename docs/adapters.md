# Adapters

An adapter translates a canonical skill into the file format and location a
specific agent expects. They live in `src/skilldeck/adapters/` and are registered
in `adapters/__init__.py` (`ADAPTERS`).

## Install locations

`--scope project` resolves paths against the current directory; `--scope global`
resolves against `$HOME`. The relative path below is the same in both cases.

| Agent   | Relative path                          | Format                         | Scopes |
|---------|----------------------------------------|--------------------------------|--------|
| claude  | `.claude/skills/<name>/SKILL.md`       | YAML frontmatter + body        | both   |
| codex   | `.codex/prompts/<name>.md`             | body as-is                     | both   |
| copilot | `.github/prompts/<name>.prompt.md`     | `description` frontmatter + body | project only |
| cursor  | `.cursor/rules/<name>.mdc`             | `description`/`alwaysApply: false` frontmatter + body | project only |
| kiro    | `.kiro/steering/<name>.md`             | `inclusion: manual` frontmatter + body | both   |

Cursor keeps user-level rules in app settings and Copilot keeps user-level
prompt files inside the VS Code profile directory, so neither has a stable
filesystem location for `--scope global` — those adapters are project-only.

> Non-Claude paths follow each tool's documented conventions; verify against
> your installed version and adjust the adapter if they differ.

## Adding a new agent

1. Create `src/skilldeck/adapters/<agent>.py` with a subclass of `Adapter`:
   - set `name`
   - implement `relative_path(skill)` and `render(skill)`
   - set `creates_skill_dir = True` if `relative_path` puts each skill in its
     own directory (like Claude's `.claude/skills/<name>/`), so uninstall
     reclaims that directory once empty; leave it unset for adapters that write
     into a directory shared by all skills
   - set `installed_glob` to a glob (relative to the scope base dir) matching
     every file the adapter installs (e.g. `.claude/skills/*/SKILL.md`), so
     `skilldeck status` can find orphaned installs
   - set `scopes = (Scope.PROJECT,)` if the agent has no stable filesystem
     location for user-level config
2. Register the instance in `ADAPTERS` in `adapters/__init__.py`.
3. Add the agent name to the `supported-agents` list of any skill it should apply
   to.

The base class handles `install`/`uninstall`, directory creation, and scope
resolution, so an adapter only describes *where* the file goes and *what* it
contains.
