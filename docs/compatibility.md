# Agent compatibility

<!-- adapter-contract: sha256:25b3bbad35d7b61fba7c89fae8217bd852da19faedcd59f5751dd9bd70e95875 -->

This page lists what skilldeck installs for each agent and where it goes. It
also covers how you then use a skill in that agent, the agent version it needs,
and how well each entry has been checked. [Adapters](adapters.md) explains the
formats, the environment variables and duplicate handling in more detail.

Each row says when it was last checked, and against which agent version and
sources. Every row was last checked on 2026-09-23. Anything that couldn't be
checked against a vendor source is marked *unverified*.

## Status

- **tested**: the agent was run at the listed version and seen to load a
  skill installed at these locations.
- **supported**: the agent's own source code, shipped binary or vendor
  documentation at the listed version confirms the locations, format and
  variables. The agent itself was not run against them.
- **experimental**: skilldeck installs as described, but one of these holds:
  - a vendor source contradicts part of the row
  - the format is deprecated, or doesn't load on some of the agent's surfaces
  - the only evidence is a related vendor package, such as an SDK that
    bundles the agent's loader, rather than the agent or its documentation

  Read the notes before relying on it.

Status covers the agent side, and is kept up to date by hand, like the
minimum versions, the dates and the notes. Every adapter's own side is
tested the same way, whatever its status: on every pull request, on Linux,
macOS and Windows, CI checks the exact bytes, paths and stamp it writes, and
checks this page's path, "Moved by" and scope-error text against them (see
[Contract tests](#contract-tests)).

## Matrix

`<name>` is the skill's name. `~` is your home directory.

| Adapter (`--agent`) | Status | `--scope project` | `--scope global` | Moved by (global only) | Minimum agent version | Last checked |
|---|---|---|---|---|---|---|
| `claude` | tested | `.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` | `CLAUDE_CONFIG_DIR`, to `$CLAUDE_CONFIG_DIR/skills`; an empty value is refused | Claude Code 2.0.20 (project skills fixed in 2.0.24) | 2026-09-23, Claude Code 2.1.281 |
| `codex` | supported | `.agents/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` | nothing (`CODEX_HOME` doesn't move it) | Codex 0.95.0 | 2026-09-23, Codex source at `rust-v0.156.1` |
| `copilot` | supported | `.github/skills/<name>/SKILL.md` | `~/.copilot/skills/<name>/SKILL.md` | `COPILOT_HOME`, to `$COPILOT_HOME/skills` (Copilot CLI only) | VS Code 1.109; Copilot CLI 0.0.371; the cloud agent and code review have no version | 2026-09-23, GitHub docs, VS Code source, Copilot CLI changelog up to 1.0.88 |
| `cursor` | experimental | `.cursor/skills/<name>/SKILL.md` | `~/.cursor/skills/<name>/SKILL.md` | nothing in `@cursor/sdk`; the Cursor app and CLI are *unverified* | *unverified* | 2026-09-23, the skills loader in `@cursor/sdk` 1.0.32 only |
| `kiro` | supported | `.kiro/skills/<name>/SKILL.md` | `~/.kiro/skills/<name>/SKILL.md` | `KIRO_HOME`, to `$KIRO_HOME/skills` (Kiro CLI; the IDE is *unverified*) | *unverified* | 2026-09-23, Kiro CLI 2.24.0 (binary and embedded docs); the IDE from Kiro's docs only |
| `copilot-prompt` | experimental | `.github/prompts/<name>.prompt.md` | not supported | n/a | *unverified* | 2026-09-23, VS Code source and docs |
| `cursor-rule` | experimental | `.cursor/rules/<name>.mdc` | not supported | n/a | *unverified* | 2026-09-23, the rules loader in `@cursor/sdk` 1.0.32 only |
| `kiro-steering` | experimental | `.kiro/steering/<name>.md` | `~/.kiro/steering/<name>.md` | `KIRO_HOME`, to `$KIRO_HOME/steering` (Kiro CLI; the IDE is *unverified*) | *unverified* | 2026-09-23, Kiro CLI 2.24.0 embedded docs; Kiro's docs mirror |

The first five are the native adapters that `--agent all` selects. The last
three are opt-in [legacy adapters](adapters.md#legacy-adapters) for agent
versions that predate skills.

When a variable in the "Moved by" column is set, skilldeck needs an absolute
path in it. It refuses a relative one, because the agent would resolve it
against whatever directory it was started in. `COPILOT_HOME` and `KIRO_HOME` count as unset
when empty. See [Environment variables](adapters.md#environment-variables).

Asking `copilot-prompt` or `cursor-rule` for `--scope global` fails, and the
error names what works instead. `install` also points at the agent's native
adapter:

```text
error: cursor-rule does not support --scope global: it has no stable file location for that scope. Use --scope project, or --agent cursor (Agent Skills), which supports --scope global
```

`status`, `uninstall` and `update` name only `--scope project`, because the
native adapter's files are different ones:

```text
error: cursor-rule does not support --scope global: it has no stable file location for that scope. Use --scope project
```

## Using a skill in each agent

### `claude`: Claude Code

- **Invoked** by typing `/<name>` (the folder name). Claude also uses a skill
  on its own when the task matches its `description`. Project skills load
  from the directory Claude Code starts in and every parent up to the
  repository root.
- **Evidence**: `code.claude.com/docs/en/skills.md` lines 120–121 and 138;
  `env-vars.md` line 403 and `claude-directory.md` line 1435
  (`CLAUDE_CONFIG_DIR`); `anthropics/claude-code@d78be94` `CHANGELOG.md` lines
  6648 (2.0.20) and 6626 (2.0.24). Claude Code 2.1.281 was run: project and
  personal skills loaded, `CLAUDE_CONFIG_DIR` moved personal skills to
  `$CLAUDE_CONFIG_DIR/skills`, and `.agents/skills` was not read.
- **Unverified**: 2.0.20 as the first version rests on the changelog alone,
  as no older build was run. The behaviour of an empty `CLAUDE_CONFIG_DIR` was
  observed in 2.1.281 only and is undocumented.

### `codex`: OpenAI Codex

- **Invoked** by mentioning `$<name>` in a prompt or picking the skill from
  `/skills` in the TUI. Codex also uses a skill when the task clearly
  matches its description. Codex keeps every copy of a skill it finds, so
  install each skill at one scope only. With two copies, a plain `$name`
  may not resolve: one of Codex's two skill-selection paths requires the
  name to be unique, and the other takes the first match. Which Codex
  surfaces use which path is *unverified*.
- **Evidence**: `openai/codex@17cd2834`, whose skill-loading files match
  tag `rust-v0.156.1`: `codex-rs/ext/skills/src/host_roots.rs` lines 95–108 and
  142–154, `codex-rs/skills/src/mentions.rs` line 41,
  `codex-rs/skills/src/selection.rs` lines 188–190 (unique name required),
  `codex-rs/ext/skills/src/selection.rs` lines 65–75 (first match),
  `codex-rs/ext/skills/src/catalog_prompt.rs` lines 3–8, and commits
  `39a6a84097` (`rust-v0.94.0`) and `e24058b7a8` (`rust-v0.95.0`).
- **Unverified**: Codex's own skills documentation couldn't be fetched, and
  Codex was not run. The IDE extension and Codex cloud were not checked.

### `copilot`: GitHub Copilot

- **Invoked** automatically when the task matches the skill's description,
  in VS Code, the Copilot CLI, the cloud agent and code review. You can also
  type `/<name>` in VS Code chat or the Copilot CLI. A skill added while a
  Copilot CLI session is running needs `/skills reload`.
- **Evidence**: `github/docs@7922319f`
  `content/copilot/concepts/agents/about-agent-skills.md` lines 27–28,
  `cli-command-reference.md` lines 1141–1155 and `cli-config-dir-reference.md`
  lines 378–386; `microsoft/vscode@5dfa2a72` `promptFileLocations.ts` lines
  172–179; `microsoft/vscode-docs@44133f07` `release-notes/v1_109.md` lines
  449 and 455; `github/copilot-cli@57dd2440` `changelog.md` line 2886
  (0.0.371).
- **Unverified**: how VS Code's Agent Host sessions find skills (the Copilot
  SDK they use is closed source), including whether they honour
  `COPILOT_HOME`. Also unchecked: the skill folders Visual Studio and
  JetBrains use, and how the Copilot CLI treats an empty `COPILOT_HOME`.
  Copilot was not run.

### `cursor`: Cursor

- **Invoked**: in the SDK's loader, each skill is offered to the agent with
  its description, and the agent decides when to use it. That choice is made
  on Cursor's servers, so it is *unverified*. Cursor documents `/<name>` only
  for skills installed from a plugin; for skills in `.cursor/skills` it is
  *unverified*.
- **Experimental** because all the evidence comes from Cursor's
  `@cursor/sdk` package, which bundles Cursor's own skills loader, and from
  Cursor's SDK cookbook. Nobody checked that the Cursor app and the
  `cursor-agent` CLI load skills from the same folders, or that no
  environment variable moves them there. The SDK itself loads project and
  user skills only when its `settingSources` option asks for them (none by
  default).
- **Evidence**: npm `@cursor/sdk` 1.0.32 `dist/esm/34.js` (the bundled skills
  loader's folder table, byte offset 552915); `cursor/cookbook@6733ef81`
  `sdk/dag-task-runner/README.md` lines 146–152. The only Cursor variable
  found, `CURSOR_DATA_DIR`, moves `~/.cursor/projects`, not skills.
- **Unverified**: Cursor's docs and changelog couldn't be reached, so the
  first release with skills is unknown, and so is the app's own behaviour.
  Cursor was not run.

### `kiro`: Kiro

- **Invoked** automatically: Kiro reads each skill's name and description
  when a chat session starts, and loads the whole skill when a request
  matches. You can also type `/<name>`, and any text after it is passed
  along. `/context show` lists the loaded skills. In Kiro CLI, a prompt file
  `.kiro/prompts/<name>.md` of the same name takes precedence over the skill.
- **Evidence**: the Kiro CLI 2.24.0 binary (its default
  `skill://.kiro/skills/*/SKILL.md` resource) and its embedded docs
  (`docs/features/skills.md`, and `docs/commands/chat.md` for `KIRO_HOME`);
  `kirodotdev/KiroCrew@f1f891b` `docs/reference/kiro-cli/skills.md`, a mirror
  of `kiro.dev/docs/skills`, which covers the IDE and CLI together.
- **Unverified**: the live kiro.dev docs and the IDE couldn't be reached, so
  the first release with skills is unknown, as is whether the IDE honours
  `KIRO_HOME`. Nobody saw a skill load at runtime, because Kiro CLI chat
  needs a login.

### `copilot-prompt`: Copilot prompt files (legacy)

- **Invoked** by hand only: `/<name>` in chat, **Chat: Run Prompt**, or the
  editor's play button. `agent: agent` makes it run in agent mode, where it
  can run `git diff`.
- **Experimental** because prompt files load only in VS Code's local agent,
  Visual Studio and JetBrains (preview). The Copilot CLI and GitHub.com don't
  load them, and VS Code has deprecated them for its Agent Host sessions,
  which don't load them either. Use `copilot` where you can.
- **Evidence**: `microsoft/vscode@5dfa2a72` `chatWidget.ts` lines 4127–4145 (a
  prompt's `agent` sets the mode) and `promptFileLocations.ts`;
  `microsoft/vscode-docs@44133f07`
  `docs/agent-customization/prompt-files.md` line 28 (not loaded by the Agent
  Host); GitHub's Copilot customization cheat sheet in `github/docs@7922319f`
  (which surfaces load prompt files).
- **Unverified**: the minimum VS Code version, and whether VS Code now uses
  the Agent Host by default.

### `cursor-rule`: Cursor rules (legacy)

- **Invoked** when the agent asks for it: the SDK's loader treats a rule with
  a `description` and `alwaysApply: false` as one the agent may request, and
  offers it with its description. When the agent pulls it in is decided on
  Cursor's servers, so it is *unverified*.
- **Experimental** for the same reason as `cursor`: the evidence comes from
  `@cursor/sdk` only, not the Cursor app.
- **Evidence**: npm `@cursor/sdk` 1.0.32 `dist/esm/34.js`, which loads
  `.cursor/rules/**/*.mdc` and reads `.mdc` frontmatter one line at a time
  (byte offset 565213). Running that reader showed that a folded description
  is cut off, which is why this adapter writes it on one line.
- **Unverified**: the minimum Cursor version, whether the Cursor app loads
  rules the same way, and whether its `.mdc` reader matches the SDK's. No
  vendor source deprecates `.mdc` rules, but none rules it out either.

### `kiro-steering`: Kiro steering files (legacy)

- **Invoked** by hand: `#<name>` in the Kiro IDE, or `/context add` in Kiro
  CLI.
- **Experimental** because Kiro's own sources disagree about the CLI. The
  docs embedded in Kiro CLI 2.24.0 say an `inclusion: manual` file loads only
  on request. Kiro's mirror of the current steering page says Kiro CLI
  ignores inclusion modes and loads every steering file. Kiro CLI before
  2.19.0 is also reported to load them all. Where that happens, every review
  prompt is in every session, so prefer `kiro`.
- **Evidence**: Kiro CLI 2.24.0 embedded `docs/features/steering-files.md`,
  and the binary string "excluding steering file from context (non-always
  inclusion mode)"; `kirodotdev/KiroCrew@f1f891b` `steering.md` lines 38–42.
- **Unverified**: which Kiro CLI engine or version the "every steering file
  loads" statement applies to, and the 2.19.0 report.

The full list of sources, with paths and line numbers, is in
[Adapters: Sources](adapters.md#sources).

## Contract tests

`tests/fixtures/adapter-contracts/` pins each adapter's side of this table:

- `skill/contract-demo/` is a small synthetic skill. Its description needs
  YAML quoting and folding, and its body has non-ASCII text.
- `contracts.json` gives each adapter's project and global paths, the text
  its `--scope global` error must contain if it is project-only (for
  `install` and for other commands), and its expected frontmatter. It also
  says where a global install goes when each environment variable is set to
  an absolute path, left empty, or set to a relative path.
- `<adapter>/` holds the exact file the adapter installs, stamp included.

The directory must hold exactly these files, and nothing else.

`tests/test_adapter_contracts.py` enforces the following:

- It installs the skill with every adapter into temporary directories and
  checks the results against these fixtures byte for byte. The fixtures are
  committed with LF line endings (`.gitattributes`), so the comparison is
  exact on Windows too.
- It checks each matrix row's project and global cells against the contract,
  and "not supported" and "n/a" for a project-only adapter.
- The "Moved by" cell must name exactly the variables that move the global
  install, each with its target, and must mention any variable the contract
  says doesn't move it.
- The quoted scope errors must match the real messages.

It doesn't check status, minimum versions, the dates or the per-agent notes.
Those are kept up to date by hand.

The `adapter-contract` comment at the top of this page is a SHA-256 digest of
the contract files: the expected files, the synthetic skill, and
`contracts.json` without its `_about` notes. When an adapter's format or
location changes, the fixtures must change, and then the test fails until
this page and `CHANGELOG.md` are updated:

1. Regenerate the expected files with
   `SKILLDECK_UPDATE_CONTRACTS=1 uv run --locked --extra dev pytest tests/test_adapter_contracts.py`,
   and review the diff.
2. Update the affected rows above: status, paths, versions, and the date
   and agent version they were checked against.
3. Replace the `adapter-contract` line with the one the test prints.
4. Add a CHANGELOG entry under `[Unreleased]` that mentions the first 12
   characters of the digest (`sha256:<12 hex>`). The test looks for it in
   `[Unreleased]` or in the newest dated section. The newest dated section
   counts because cutting a release moves the entry there and leaves
   `[Unreleased]` empty. An older section doesn't count.

## When a vendor changes a location or format

Agents move skill folders, rename variables and retire formats. skilldeck
handles a change like this:

1. **Confirm it** in a primary source: the vendor's source code at a release
   tag, a shipped binary, or the vendor's docs. A blog post, forum thread or
   issue title is only a lead.
2. **Deprecated but still loading**: mark the row *experimental*, and note
   the deprecation and the agent version that announced it. Installs keep
   working, so there is no need for an immediate release.
3. **Moved or replaced**: point the native adapter at the new location or
   format. While any agent version still in use reads the old one, keep it as
   an opt-in legacy adapter. Add it to `MIGRATIONS` so `skilldeck migrate`
   moves existing installs. If the vendor removes the old format outright,
   keep it only as a migration source, not an install target, as was done
   when Codex dropped custom prompts in 0.118.0.
4. **Update the contract**: regenerate the fixtures, and update this page and
   the CHANGELOG ([above](#contract-tests)). Mark the entry **Breaking:** if
   existing installs have to move.
5. **Urgent**: if a current agent release stops loading what skilldeck
   installs, skills disappear from that agent without any error. Release the
   fix as soon as it merges, following [Releasing](releasing.md), instead of
   batching it with other changes. Have the changelog entry tell users to run
   `skilldeck migrate` or `skilldeck update`.

When skilldeck itself drops an agent or a format that the vendor still
supports, it deprecates it first and waits a notice period: see
[Removing an agent or format](lifecycle.md#removing-an-agent-or-format).
