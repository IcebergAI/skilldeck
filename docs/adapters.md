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

`--scope global` always resolves against `$HOME`. skilldeck does not yet read
`CODEX_HOME` or `CLAUDE_CONFIG_DIR`. If you have moved Codex's or Claude Code's
config directory with one of them, a global install lands in the default
location (`~/.codex`, `~/.claude`), which that agent won't read. Support for
these variables is planned alongside the adapter updates. Until then, use
`--scope project`, or make the default location a symlink to your configured
directory (see [Symlinks](#symlinks)).

## Stamps: what skilldeck will overwrite or delete

Every installed file ends with a `skilldeck` stamp recording the skill name, its
version, and a hash of the content (`src/skilldeck/stamp.py`). The stamp
decides how the file at an install path is treated:

| State | Meaning | `install` / `update` | `uninstall` |
|-------|---------|----------------------|-------------|
| up to date / stale | stamped and unedited | overwritten | deleted |
| modified | stamped, edited since install | only with `--force` | only with `--force` |
| unmanaged file | a regular file with no stamp, or not UTF-8 | `install --force` only; `update` skips it | only with `--force` |
| symlink | see [Symlinks](#symlinks) | never | only with `--force`, which removes the link, not its target |
| directory or special file | a directory, FIFO, socket or device | never | never |

Files installed by skilldeck 0.3.0 or earlier have no stamp, so they count as
unmanaged: after upgrading, run `install --force` once to adopt them (or
`uninstall --force` to remove them).

`uninstall --force` doesn't read the file, so it can also remove one that
skilldeck can't read. `install` and `update` refuse to replace a file you have
made read-only, even with `--force`, as a plain write would; make it writable
first.

`install` writes to a temporary file in the same directory and renames it
over the destination (`os.replace`). An interrupted install leaves the old file
or the new one, never a half-written one. A new file gets the permissions a
normal write would. An overwritten file keeps its own, except that the owner
is always given read access, so the agent can read the skill.

`status` also reports **orphans**: files matching an adapter's
`installed_glob` that carry a skilldeck stamp but belong to no bundled skill
(for example, a skill that has since been removed from skilldeck). Most of these
directories (`.codex/prompts`, `.github/prompts`, `.cursor/rules`,
`.kiro/steering`, and `~/.claude/skills` in global scope) also hold your own
files. Files without a stamp, symlinks, and files that can't be read as UTF-8
are never listed.

## Symlinks

skilldeck never creates symlinks, so it treats a symlink **at an install path**
as something you put there:

- `install` refuses to write through it, even with `--force`, because that
  would overwrite the link's target. Remove the link first if you want
  skilldeck to manage that path.
- `status` and `update` don't follow it: a link to a stamped file elsewhere
  (for example, another project's install) is reported as unmanaged and never
  counted as an install here.
- `uninstall` refuses it without `--force`. With `--force` it removes the link
  itself; the link's target is never touched.

Symlinked **parent directories** are followed on purpose. For example,
`.cursor/rules -> ../shared/rules`, or a `~/.claude` that a dotfiles manager
links into a repository. Sharing one rules directory between projects, or
keeping agent config in dotfiles, is a common setup, and in those cases the
real directory is where the agent reads from. skilldeck checks only the final
path component. If an install directory is a symlink, installs and uninstalls
land wherever it points.

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

The base class handles `install`/`uninstall` (including the stamp checks,
symlink handling and atomic writes described above), directory creation, and
scope resolution, so an adapter only describes *where* the file goes and *what*
it contains.
