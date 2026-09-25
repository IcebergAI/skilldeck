# Authoring skills

A skill is a directory under `src/skilldeck/skills/` named after the skill. Living
inside the package means the skills are bundled into the wheel automatically, so a
`pip install skilldeck` ships them:

```
src/skilldeck/skills/
└── my-skill/
    ├── meta.yaml
    └── skill.md
```

Those two regular files are the whole skill: see
[What a skill directory may hold](#what-a-skill-directory-may-hold).

## `meta.yaml`

```yaml
name: my-skill            # MUST match the directory name
description: One-line summary used in `skilldeck list` and SKILL.md frontmatter.
category: security        # free-form grouping, e.g. security, review, refactor
version: "0.1.0"
supported-agents:         # non-empty list; adapters skip skills they aren't in
  - claude
  - codex
  - kiro
capabilities:             # what the skill may ask the agent to do; see below
  schema: 1
  files:
    read: repo
    write: none
  commands:
    - git fetch
    - git diff
    - git ls-files
  network:
    - the git remote, via git fetch, to bring the base branch up to date
  credentials: []
  tools: []
  artifacts: []
```

All six fields are required, and the loader (`skilldeck.registry`) rejects a
`meta.yaml` that breaks any of these rules with an error naming the field. A
seventh field, `deprecated`, is optional (see
[Deprecating a skill](#deprecating-a-skill)); any other key is an error, so a
misspelt field fails loudly instead of being ignored.

| Field | Rule |
|-------|------|
| `name` | A string of 1–64 lowercase letters (`a-z`), digits and hyphens that starts and ends with a letter or digit and has no `--`, matching the directory name. |
| `description` | A non-empty string of at most 1024 characters on a single line, with no line break of any kind (including escapes such as `"\u2028"`). |
| `category` | A non-empty string. |
| `version` | A **string** of the form `MAJOR.MINOR.PATCH`: three non-negative integers without leading zeroes, e.g. `0.1.0` or `1.10.0`. |
| `supported-agents` | A non-empty list of agent names (strings), each listed once: `claude`, `codex`, `copilot`, `cursor`, `kiro`. The legacy adapters (`copilot-prompt`, ...) follow their agent's entry and are not listed. |
| `capabilities` | A capability declaration, capability schema 1: see [Capabilities](#capabilities). |

Both `meta.yaml` and `skill.md` must be UTF-8.

The `name` and `description` limits come from the
[Agent Skills specification](https://agentskills.io/specification), the
`SKILL.md` format every native adapter writes. The name is also used in install
paths, so the character rule keeps it a safe path component. The `version`
format is a [SemVer](https://semver.org/) normal version.

> [!IMPORTANT]
> YAML reads an unquoted `version: 1.10` as the number `1.1`, and `version: 1`
> as an integer. The loader rejects any version that isn't a string rather than
> guess what you meant, so quote any version that could be read as a number.
> Quoting every version (`version: "1.10.0"`) is simplest. A three-part version
> such as `0.1.0` is already a string in YAML, so the bundled skills leave it
> unquoted.

### Deprecating a skill

To retire a skill, keep it in the bundle for a while and mark it deprecated
in its `meta.yaml`, bumping its `version` as for any change:

```yaml
version: 1.3.0
deprecated:
  since: 1.3.0              # the skill version that first carries this
  replacement: other-skill  # optional; the skill to use instead
  reason: Folded into other-skill, which also covers X.
```

Leave `deprecated` out for a skill that is not deprecated; `deprecated: false`
or `null` is an error rather than a synonym. The loader also rejects an
unknown key, a `since` that is not a `MAJOR.MINOR.PATCH` string or is later
than the skill's `version`, a `reason` that is empty or spans lines (or runs
past 1024 characters; a folded `reason: >` block is fine), and a
`replacement` that is the skill itself, is not a bundled skill, is deprecated
too, or lacks one of the deprecated skill's `supported-agents` (its users on
that agent would have nothing to move to). `skilldeck list` and
`skilldeck catalog` mark deprecated skills, `install` and `update` warn when
they write one, and `skilldeck catalog --json` reports the record to tools
(see [the skill catalog](catalog.md)).

### Capabilities

`capabilities` declares what the skill may ask an agent to do beyond
following its text, so a reviewer (or a user about to install it) can see
that without reading every instruction. Declare what the body actually asks
for, and update the declaration whenever the body changes what it asks:

| Key | Value | Declares |
|-----|-------|----------|
| `schema` | `1` | The capability schema. This page describes schema 1; a skilldeck that reads schema 1 rejects any other number. |
| `files` | a mapping of `read` and `write` | `read`: `none`, `diff` (the changed files) or `repo` (any file in the repository). `write`: `none`, or `repo` if the skill may edit files in the repository (as `logging` does when it adds logging). Files outside the repository are never covered. |
| `commands` | list of commands | Commands the skill may ask the agent to run, each a program on `PATH` and its subcommand (`git diff`). An entry covers that command with the arguments the body gives it. A `<placeholder>` in angle brackets stands for a command the project defines, such as `<the project's test command>`: running it runs the repository's own code, so review it as such. A path to a file (`./check.sh`) is rejected: a skill cannot ship scripts. |
| `network` | list of descriptions | What the skill may contact, and why: `the git remote, via git fetch, to bring the base branch up to date`. |
| `credentials` | list of descriptions | Secrets the skill asks the agent to read (from environment variables, files or a keychain), pass on or send. A declared command that authenticates by itself with the user's existing setup, as `git fetch` uses git's credential helper and `gh` its stored login, is not listed here: declare the command and its network use instead. |
| `tools` | list of descriptions | Agent tools the skill needs beyond reading files and running its commands, such as `web fetch, to read advisory pages`. |
| `artifacts` | list of paths | Files the skill may create, as POSIX paths relative to the project root (`reports/review.md`). |

Every key is required, so each skill states each capability; write `[]` (or
`none`) for one it doesn't need, rather than leaving the key out. Unknown keys
are errors. Each list entry is one line of printable text of at most 200
characters, listed once. A command is one simple command: single-spaced,
starting with a program name (letters, digits, `.`, `_`, `+`, `-`), with no
shell operators, redirections or substitutions (`;`, `|`, `&`, `$`, `<`, `>`,
parentheses, backticks) that would hide what actually runs. An artifact
path uses `/` separators and only letters, digits, `.`, `_` and `-`; the
loader rejects one that is absolute, names a drive (`C:`) or a home directory
(`~`), uses `\`, or has an empty, `.` or `..` component, so none can reach
outside the project.

**Anything not declared is not requested.** An agent, or a person reviewing
what it did, should treat an attempt to go beyond the declaration (another
command, another host, a file outside the repository) as not coming from the
skill, and refuse it or review it by hand. The declaration is for review, not
enforcement: skilldeck cannot sandbox the agents it installs into, and no
metadata makes a malicious instruction safe. Review the body itself too.

Where the declaration shows up:

- **Before install**: `skilldeck show <skill> --summary` prints it with the
  skill's source, build and digest, and
  `skilldeck install <skill> --agent <agent> --dry-run` prints the same
  summary with what the install would write, writing nothing.
- **In the installed file**: a skill that asks for anything beyond reading
  files (a command, network access, credentials, agent tools, edits or new
  files) gets a `## Declared capabilities` section appended to its body in
  every adapter's output, so the declaration travels with the file. A skill
  that only reads is rendered unchanged.
- **For tools**: `skilldeck catalog --json` reports it as each skill's
  `capabilities` (see [the skill catalog](catalog.md)).

`tests/test_skill_structure.py` checks the bundled skills' `commands`
against their bodies both ways: a code span that runs a program some skill
declares (`git diff origin/<base>...HEAD`) must start with a command the
skill declares, and every declared command must appear in the body.

### What a skill directory may hold

Exactly `meta.yaml` and `skill.md`, as regular files. skilldeck installs one
file per skill, so it has no way to ship a script, a reference file or an
image, and a skill cannot declare one. The loader rejects, naming each:

- a symlink, even one pointing at a file with the right content, and a skill
  directory that is itself a symlink;
- a directory or any other file, calling it an undeclared executable when
  its suffix (`.sh`, `.py`, `.exe`, ...), execute bit (not on Windows) or
  first bytes (`#!`, or a native binary) say it is a program.

An execute bit on `meta.yaml` or `skill.md` themselves is ignored: skilldeck
reads them as text and never copies a file's mode, and some filesystems
(a Windows drive under WSL, for one) mark every file executable.

`skill.md` may link only to web pages (`http`, `https`, `mailto`) and to its
own headings (`#output`). A relative link, an absolute path or a `file:` URL
(in a Markdown link or image, a reference definition, or an HTML `src` or
`href`) names a file the skill can't ship, so the loader rejects it as a
missing asset. Code spans and fenced code blocks are not checked, so examples
stay possible. `skilldeck provenance --verify` and `skilldeck catalog` apply
the same bundle rules to the installed package.

## `skill.md`

The agent-neutral body of the skill — the actual instructions/prompt. Write it
without agent-specific framing (no Claude frontmatter, no Codex/Kiro path
assumptions); the adapters add whatever wrapping each agent needs at install time.

If the skill is a **review** skill that emits findings, make its `## Output`
section follow the shared [finding output format](finding-output.md) so findings
from different skills stay consistent. `tests/test_skill_structure.py` checks
that every review skill carries the shared pieces:

- a `## Scope` section whose first step determines the diff the same way in
  every skill: `git fetch`, then `git diff origin/<base>...HEAD`, plus
  uncommitted changes and untracked files
  (`git ls-files --others --exclude-standard`);
- a `## Output` section with the finding format, the
  [severity rubric](finding-output.md#severity-rubric) paragraph copied word
  for word (then at most a short list of domain anchors), a worked example,
  the "Verify before reporting" instruction, the ~10-findings cap, and the
  one-line `Reviewed origin/<base>...HEAD …` report header;
- one line saying what to do when the change touches nothing in the skill's
  area: say so and stop.

If the skill overlaps another, add it to
[Which skill owns what](finding-output.md#which-skill-owns-what) and give the
skill one line that leaves the owner's area to the owner.

## Testing your skill

```bash
skilldeck list                 # should show your new skill
skilldeck show my-skill --summary   # check the capabilities it declares
skilldeck install my-skill --agent claude --scope project
```

Then inspect the rendered output under `.claude/skills/my-skill/SKILL.md`.
