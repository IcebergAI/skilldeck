# Adapters

An adapter translates a canonical skill into the file format and location a
specific agent expects. They live in `src/skilldeck/adapters/` and are registered
in `adapters/__init__.py`.

Every supported agent now reads [Agent Skills](https://agentskills.io/specification):
a `<name>/` folder holding a `SKILL.md` whose YAML frontmatter carries the
skill's `name` and `description` above the Markdown body. Each agent's **native
adapter** (`ADAPTERS`, named after the agent) writes that format into the
agent's own skills folder, and all five render byte-identical files; only the
folders differ. The formats skilldeck used before remain available as opt-in
[legacy adapters](#legacy-adapters) for agent versions that predate skills.

## Install locations

`--scope project` resolves against the current directory, so run it from the
repository root, where every agent looks. `--scope global` resolves against
your home directory, or against the agent's config directory when you have
moved it with an [environment variable](#environment-variables).

| Agent (`--agent`) | `--scope project` | `--scope global` | Moved by | Needs |
|---|---|---|---|---|
| `claude` | `.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` | `CLAUDE_CONFIG_DIR` | Claude Code 2.0.20+ |
| `codex` | `.agents/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` | nothing (not `CODEX_HOME`) | Codex 0.95.0+ |
| `copilot` | `.github/skills/<name>/SKILL.md` | `~/.copilot/skills/<name>/SKILL.md` | `COPILOT_HOME` | VS Code 1.109+; Copilot CLI with skills (0.0.371+) |
| `cursor` | `.cursor/skills/<name>/SKILL.md` | `~/.cursor/skills/<name>/SKILL.md` | nothing | a Cursor release with skills (see below) |
| `kiro` | `.kiro/skills/<name>/SKILL.md` | `~/.kiro/skills/<name>/SKILL.md` | `KIRO_HOME` | a Kiro release with skills (see below) |

`skilldeck show <skill> --agent <agent>` prints exactly what gets written
(minus the [stamp](#stamps-what-skilldeck-will-overwrite-or-delete)).

`--agent all` selects these five native adapters and nothing else; a legacy
adapter runs only when you name it.

### Minimum agent versions

- **Claude Code** added skills in 2.0.20 and fixed project-level skills in
  2.0.24.
- **Codex** reads `.agents/skills` in a repository from 0.94.0 and
  `~/.agents/skills` from 0.95.0, so 0.95.0 covers both scopes. Codex 0.76.0
  through 0.141.0 reject a description longer than 1024 characters, which
  skilldeck's own limit already rules out.
- **GitHub Copilot**: VS Code enables Agent Skills by default from 1.109
  (1.108 has them behind the experimental `chat.useAgentSkills` setting).
  Skills first appear in the Copilot CLI changelog at 0.0.371. The cloud
  agent and code review on GitHub.com have no version. GitHub documents only
  `.github/skills` for Copilot code review.
- **Cursor**: the first release with skills could not be verified (Cursor's
  changelog was unreachable). The locations above come from the skills loader
  in Cursor's own `@cursor/sdk` package.
- **Kiro**: confirmed in Kiro CLI 2.24.0, and Kiro's skills documentation
  covers the IDE and the CLI together. The first release of either with
  skills could not be verified.

On an older version, use the matching [legacy adapter](#legacy-adapters)
instead.

### Environment variables

skilldeck reads these variables from its own environment. Each one moves the
agent's whole user config directory, so a global install goes to
`$VAR/skills/<name>/SKILL.md` (`$KIRO_HOME/steering/<name>.md` for
`kiro-steering`). The value must be an absolute path: an agent resolves a
relative one, or a `~` your shell didn't expand (as in
`export CLAUDE_CONFIG_DIR="~/claude"`), against the directory it was started
in, which skilldeck can't know. skilldeck reports an error for that agent
instead of guessing.

- **`CLAUDE_CONFIG_DIR`**: when it is set, Claude Code reads personal skills
  only from `$CLAUDE_CONFIG_DIR/skills`, never `~/.claude/skills`. An *empty*
  `CLAUDE_CONFIG_DIR` does not mean "unset" to Claude Code: it resolves the
  empty path against its working directory, so personal skills come from a
  `skills` folder in whatever directory Claude Code starts in. skilldeck
  therefore refuses a global `claude` operation while the variable is set but
  empty. Unset it, or give it an absolute path. Claude Code also honours
  `CLAUDE_CONFIG_DIR` from the `env` block of `~/.claude/settings.json` or
  managed settings. skilldeck doesn't read those files, so if you set it
  there, export it in the shell you run skilldeck from too.
- **`COPILOT_HOME`** replaces `~/.copilot` for Copilot CLI. VS Code's local
  agent reads `~/.copilot/skills` whatever the variable says, so with
  `COPILOT_HOME` set a global install reaches the CLI but not that VS Code
  agent. skilldeck treats an empty value as unset, as VS Code's Agent Host
  code does; how the Copilot CLI treats one is unverified.
- **`KIRO_HOME`** replaces `~/.kiro` for Kiro CLI; Kiro treats an empty value
  as unset, and so does skilldeck. Whether the Kiro IDE honours `KIRO_HOME` is
  unverified.
- **`CODEX_HOME`** is not used. Codex reads `~/.agents/skills` from your home
  directory whatever `CODEX_HOME` says. It also still loads
  `$CODEX_HOME/skills`, but its source labels that location deprecated.

Project-scope installs don't depend on any of these.

## Where each agent looks, and duplicates

Several agents also read other agents' folders:

| Agent | Project folders it reads | User folders it reads |
|---|---|---|
| Claude Code | `.claude/skills` (start directory up to the repository root) | `~/.claude/skills`, or `$CLAUDE_CONFIG_DIR/skills` |
| Codex | `.agents/skills` (repository root down to the working directory), `.codex/skills` | `~/.agents/skills`, `$CODEX_HOME/skills` (deprecated), `/etc/codex/skills` |
| Copilot | `.github/skills`, `.agents/skills`, `.claude/skills` | `~/.copilot/skills`, `~/.agents/skills`; VS Code's local agent also `~/.claude/skills` |
| Cursor | `.cursor/skills`, `.agents/skills`; `.claude/skills` and `.codex/skills` when third-party extensibility is on | the same folders under `~` |
| Kiro | `.kiro/skills` | `~/.kiro/skills`, or `$KIRO_HOME/skills` |

So one skill can be found more than once:

- **Copilot** finds a skill you installed for Claude, Codex and Copilot three
  times. It keeps one copy per name: the CLI takes `.github/skills` first, then
  `.agents/skills`, then `.claude/skills`, and VS Code's local agent takes
  `.agents/skills` first. The copies skilldeck writes are identical, so it
  doesn't matter which one wins, as long as you update them together.
- **Cursor** always reads `.agents/skills`, and also `.claude/skills` when
  third-party extensibility is on. It keeps the first copy per name, in the
  order `.cursor`, `.claude`, `.codex`, `.grok`, `.agents`.
- **Codex** keeps every copy it finds, and a plain `$name` mention only
  resolves when exactly one enabled skill has that name. Installing a skill
  for Codex at both project and global scope (or next to a copy of your own
  in `.codex/skills` or `~/.codex/skills`) breaks `$name` for it.
- **An old format next to a skill** is not merged at all: VS Code lists a
  Copilot prompt file and a skill of the same name as two `/name` commands,
  and Cursor loads both the rule and the skill.
  [`skilldeck migrate`](#migrating-from-the-old-formats) replaces the old
  file instead of adding a second copy.

### Recommended setup

Install each skill **once per agent**, at **one scope**:

1. For a team repository, install from the repository root for each agent
   the team uses, and commit the result:

   ```bash
   skilldeck install --all --agent claude --agent copilot   # or --agent all
   ```

   After upgrading skilldeck, run `skilldeck update --agent all`, so the
   copies Copilot and Cursor may see side by side stay identical.
2. For personal use across projects, use `--scope global` instead, and don't
   also install the same skills at project scope for that agent.
3. Don't combine an agent's native adapter with its legacy adapter, and move
   old installs with `skilldeck migrate`.

If you want a single copy for several agents, Codex, Copilot and Cursor all
read `.agents/skills`, so `--agent codex` serves all three at project scope.
Copilot code review on GitHub.com is the exception, as GitHub documents only
`.github/skills` for it. `skilldeck status --agent copilot` then reports the
skills as not installed, since skilldeck tracks each agent's own folder.

## Legacy adapters

These write each skill as a single file in the format skilldeck used before
the agents read `SKILL.md`. They apply to every skill that lists their agent in
`supported-agents` (a skill's `meta.yaml` never names them), and run only when
named with `--agent`.

| `--agent` | Writes | Scopes | Frontmatter | Works in |
|---|---|---|---|---|
| `copilot-prompt` | `.github/prompts/<name>.prompt.md` | project | `description`, `agent: agent` | VS Code's local agent, Visual Studio, JetBrains (preview); not the Copilot CLI, GitHub.com or VS Code's Agent Host |
| `cursor-rule` | `.cursor/rules/<name>.mdc` | project | `description`, `alwaysApply: false` | Cursor |
| `kiro-steering` | `.kiro/steering/<name>.md` | both (`$KIRO_HOME/steering` globally) | `inclusion: manual` | Kiro IDE (`#<name>`), Kiro CLI (`/context add`) |

- `agent: agent` makes a Copilot prompt file run in agent mode, where it can
  run `git diff` and read files. Without it the prompt runs in whatever mode
  the chat is in, which may be Ask.
- Cursor reads `.mdc` frontmatter one `key: value` line at a time rather than
  as YAML, so `cursor-rule` writes the description on a single line. (The
  Cursor adapter used to fold long descriptions onto a second line, which the
  reader in Cursor's published SDK drops.)
- Kiro loads a steering file with `inclusion: manual` only when you ask for
  it, according to the Kiro IDE docs and the docs shipped in Kiro CLI 2.24.0.
  Kiro CLI before 2.19.0 is reported to have loaded every steering file
  regardless, which puts every review prompt in every session; that report
  comes from Kiro's KiroCrew notes and could not be verified.
- Codex custom prompts (`.codex/prompts/<name>.md`) are gone. Codex only ever
  read them from `$CODEX_HOME/prompts`, never from a project, deprecated them
  in 0.117.0 and removed them in 0.118.0, so there is no Codex legacy adapter.

## Migrating from the old formats

skilldeck 0.3.0 and earlier installed Codex and Kiro skills in the old
formats, and so did development builds before the switch to `SKILL.md`, which
also had the Copilot and Cursor adapters:

| Agent | Old location | New location |
|---|---|---|
| codex | `.codex/prompts/<name>.md`, `~/.codex/prompts/<name>.md` | `.agents/skills/<name>/SKILL.md`, `~/.agents/skills/<name>/SKILL.md` |
| copilot | `.github/prompts/<name>.prompt.md` (project only) | `.github/skills/<name>/SKILL.md` |
| cursor | `.cursor/rules/<name>.mdc` (project only) | `.cursor/skills/<name>/SKILL.md` |
| kiro | `.kiro/steering/<name>.md`, `~/.kiro/steering/<name>.md` | `.kiro/skills/<name>/SKILL.md`, `~/.kiro/skills/<name>/SKILL.md` |

`skilldeck migrate --agent <agent>` (repeat `--agent`, or use `all`; add
`--scope global` for global installs) moves them. For every bundled skill with
a file at the old location it installs the native `SKILL.md`, then removes the
old file. It follows the
[stamp rules](#stamps-what-skilldeck-will-overwrite-or-delete):

- A stamped, unedited old install is migrated.
- An old file with local edits, without a stamp, or that is a symlink is left
  in place and reported. `--force` migrates it anyway: the bundled skill
  replaces your edits, and a symlink is removed while its target is kept.
- A directory at the old path is never removed.
- If the new location already holds a file with local edits, or one skilldeck
  didn't write, the old file stays and the skill is reported as an error,
  unless you pass `--force`.

Running it again is harmless: it reports `nothing to migrate`. `status` and
`update` print a one-line `hint:` for an agent with files at the old locations,
counting how many need `--force`.

Installs from skilldeck 0.3.0 and earlier carry no stamp, so they need
`--force`. The same goes for a file of your own that shares a bundled skill's
name, so check the reported paths first.

Two global-scope details: skilldeck used to write Codex prompts under
`~/.codex/prompts` whatever `CODEX_HOME` said, and that is where `migrate`
looks. Kiro steering files were likewise written under `~/.kiro/steering`,
but `migrate` looks in `$KIRO_HOME/steering` when `KIRO_HOME` is set. To clear
out old files there, run `KIRO_HOME= skilldeck uninstall --all --agent
kiro-steering --scope global` (with `--force` for unstamped ones) and install
afresh.

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
`uninstall --force` to remove them). For Codex and Kiro installs from those
versions, use [`migrate --force`](#migrating-from-the-old-formats) instead,
which also moves them to the new format.

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
(for example, a skill that has since been removed from skilldeck). The skills
folders, and the legacy adapters' `.github/prompts`, `.cursor/rules` and
`.kiro/steering`, also hold your own files and other tools' skills. Files
without a stamp, symlinks, and files that can't be read as UTF-8 are never
listed.

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
`.cursor/skills -> ../shared/skills`, or a `~/.claude` that a dotfiles manager
links into a repository. Sharing one skills directory between projects, or
keeping agent config in dotfiles, is a common setup, and in those cases the
real directory is where the agent reads from. skilldeck checks only the final
path component. If an install directory is a symlink, installs and uninstalls
land wherever it points.

## Adding a new agent

1. Create `src/skilldeck/adapters/<agent>.py`. If the agent reads Agent
   Skills, subclass `SkillMdAdapter` (`adapters/skill_md.py`) and set:
   - `name`, the agent name skills list in `supported-agents`
   - `project_dir`, the skills folder relative to the project root (e.g.
     `.claude/skills`)
   - `global_dir`, a `UserDir` (`targets.py`) for the user-level folder: the
     config directory's default under `~`, the folder inside it, and the
     environment variable that moves it, if any (e.g.
     `UserDir(".kiro", "skills", env="KIRO_HOME")`). Leave it `None` if the
     agent has no stable user-level location; the adapter is then
     project-scope only.

   For any other format, subclass `Adapter` and also implement `entry(skill)`
   (the file's path relative to the install folder) and `render(skill)`, set
   `installed_glob` to a glob relative to the install folder matching every
   file the adapter writes (so `status` can find orphans), and set
   `creates_skill_dir = True` if `entry` puts each skill in its own directory,
   so uninstall reclaims it once empty.
2. Register the instance in `ADAPTERS` in `adapters/__init__.py`. An older
   format of an existing agent is a `LegacyAdapter` (`adapters/legacy.py`) in
   `LEGACY_ADAPTERS`, and goes in `MIGRATIONS` too if `skilldeck migrate`
   should move installs out of it.
3. Add the agent name to the `supported-agents` list of any skill it should
   apply to.

The base class handles `install`/`uninstall` (including the stamp checks,
symlink handling and atomic writes described above), directory creation, and
scope resolution, so an adapter only describes *where* the file goes and *what*
it contains.

## Sources

The locations, variables and versions above were checked against these vendor
sources in September 2026:

- **Claude Code**: `code.claude.com/docs/en/skills.md` lines 120–121
  (personal and project locations), `env-vars.md` line 403 and
  `claude-directory.md` line 1435 (`CLAUDE_CONFIG_DIR` moves every `~/.claude`
  path); `anthropics/claude-code@d78be94` `CHANGELOG.md` lines 6648 (2.0.20,
  skills) and 6626 (2.0.24). The empty-`CLAUDE_CONFIG_DIR` behaviour was
  observed in Claude Code 2.1.281, whose config-directory resolver uses `??`,
  so an empty string is kept; it is undocumented and may change.
- **Codex**: `openai/codex@17cd2834` (same files as tag `rust-v0.156.1`)
  `codex-rs/ext/skills/src/host_roots.rs` lines 95–108 (`~/.agents/skills`
  from the home directory; `$CODEX_HOME/skills` "deprecated") and 142–154
  (`.agents/skills` from the project root down), and
  `codex-rs/skills/src/selection.rs` lines 188–190 (a plain name must be
  unique); commits `39a6a84097` (#10317, `rust-v0.94.0`) and `e24058b7a8`
  (#10437, `rust-v0.95.0`) for `.agents/skills`; `b8e8454b3f` (#2696, custom
  prompts in `~/.codex/prompts`), `e5de13644d` (#15076, deprecated in
  `rust-v0.117.0`) and `48144a7fa4` (#16115, removed in `rust-v0.118.0`).
- **GitHub Copilot**: `github/docs@7922319f`
  `content/copilot/concepts/agents/about-agent-skills.md` lines 27–28,
  `content/copilot/reference/copilot-cli-reference/cli-command-reference.md`
  lines 1141–1155 (CLI load order) and `cli-config-dir-reference.md` lines
  378–386 (`COPILOT_HOME`); `microsoft/vscode@5dfa2a72`
  `src/vs/workbench/contrib/chat/common/promptSyntax/config/promptFileLocations.ts`
  lines 172–179 (VS Code's skill folders) and
  `src/vs/workbench/contrib/chat/browser/widget/chatWidget.ts` lines 4127–4145
  (a prompt's `agent` sets the mode); `microsoft/vscode-docs@44133f07`
  `release-notes/v1_109.md` line 449 and
  `docs/agent-customization/prompt-files.md` line 28 (prompt files not loaded
  by the Agent Host); `github/copilot-cli@57dd2440` `changelog.md` (0.0.371).
- **Cursor**: npm `@cursor/sdk` 1.0.32, `dist/esm/34.js` (the bundled
  `local-exec` skills loader's folder table at byte offset 552915, its
  duplicate key at 559645, and the line-based `.mdc` frontmatter reader at
  565213); `cursor/cookbook@6733ef81` `sdk/dag-task-runner/README.md` lines
  146–152 (`.cursor/skills` and `~/.cursor/skills`).
- **Kiro**: the documentation embedded in Kiro CLI 2.24.0
  (`docs/features/skills.md` for the default locations,
  `docs/commands/chat.md` for `KIRO_HOME`, `docs/features/steering-files.md`
  for manual steering); `kirodotdev/KiroCrew@f1f891b`
  `docs/reference/kiro-cli/skills.md` and `steering.md`, a mirror of
  `kiro.dev/docs`.
- **Agent Skills format**: `agentskills/agentskills@69ef37e`
  `docs/specification.mdx` lines 27–28.
