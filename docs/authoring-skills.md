# Authoring skills

A skill is a directory named after the skill, holding two files:

```
my-review/
├── meta.yaml   # name, description, category, version, agents, capabilities
└── skill.md    # the agent-neutral instructions
```

Those two regular files are the whole skill: see
[What a skill directory may hold](#what-a-skill-directory-may-hold).

The bundled skills live in `src/skilldeck/skills/`, inside the package, so
they ship in the wheel. Two commands do the mechanical part of writing one:
`skilldeck new` scaffolds a skill that already has every required field and
section, and `skilldeck validate` checks a skill against every rule on this
page, offline, naming the file, the rule and the fix for each problem. Use
them as the way in; the sections after them describe the rules they apply.

## Contributing a skill to this repository

Open an issue first (see [CONTRIBUTING.md](../CONTRIBUTING.md)), then, in a
checkout:

```bash
uv run --extra dev skilldeck new my-review --category security \
  --description "Review pending changes for ..."
# write the content: replace every TODO(author) placeholder in
#   src/skilldeck/skills/my-review/skill.md, declare in meta.yaml's
#   capabilities anything it asks beyond the read-only review baseline,
#   plant a defect in evals/fixtures/my-review/ and add its SAMPLE_REPORTS
#   entry in tests/test_eval_fixtures.py, list the skill in
#   docs/finding-output.md
uv run --extra dev skilldeck validate my-review
uv run --extra dev python scripts/build_plugin.py   # regenerate the plugin tree
uv run --extra dev skilldeck validate               # every skill
uv run --extra dev pytest                           # what validate can't check
```

`validate` covers the rules on this page; the test suite also checks what it
cannot, such as each planted fixture's `SAMPLE_REPORTS`. Before you push, run
the full check suite in [CONTRIBUTING.md](../CONTRIBUTING.md).

Run the commands from the checkout with `uv run --extra dev`, so they use the
checkout's own code. `validate` runs the eval-fixture and generated-output
checks only then (see [Trust](#trust)).

## Organization skills

Skills your organization keeps for itself live in your own repository, not
in this one. Outside a skilldeck checkout there is no default skills
directory, so name yours explicitly:

```bash
skilldeck new my-review --category security --dir skills
skilldeck validate --skills-dir skills             # every skill in it
skilldeck validate --skills-dir skills my-review   # one skill, by name
skilldeck validate ./skills/my-review --json       # or by path, for CI
```

skilldeck never writes into its own installed package: `new` refuses a
directory inside it. The checks that only make sense in this repository (eval
fixtures, `docs/finding-output.md`, the generated plugin tree) are skipped,
and the report says so. `skilldeck install` installs only the skills bundled
with skilldeck; it cannot install from your directory yet.

## What `skilldeck new` writes

```bash
skilldeck new NAME --category CATEGORY [--description TEXT] [--agent AGENT]... \
  [--dir PATH] [--no-eval-fixture]
```

- `NAME/meta.yaml` with every required field: the name, `--description` (a
  placeholder if omitted), `--category`, version `0.1.0`,
  `supported-agents` listing every agent unless `--agent` names some, and
  the [capabilities](#capabilities) of a read-only review, as the bundled
  review skills declare them: read the repository, edit nothing, run
  `git fetch`, `git diff` and `git ls-files` (the commands the skeleton's
  Scope steps use), and contact the git remote. A skill with that
  declaration renders without a `## Declared capabilities` notice. When the
  skill you write asks for more (another command, an edit, a credential, an
  agent tool, a file it creates), declare it: `validate` checks the
  declaration against the body's commands.
- `NAME/skill.md`: the structure every review skill shares (see
  [`skill.md`](#skillmd)): a title spelling the name, the `## Scope` steps
  that determine the diff, and an `## Output` section with the finding
  format, the severity rubric word for word, the verify-before-reporting
  instruction, the findings cap and the report header. Wherever domain
  content goes (what the skill reviews, the checklist, the sources it rests
  on, the classifier and a worked example), it writes a `TODO(author)`
  placeholder instead. The template states no domain guidance and cites no
  source: that is the author's work, grounded in sources they fetched.
- In a checkout, `evals/fixtures/NAME/`: an `expected.yaml` and placeholder
  `base/` and `change/` files, which you turn into a fixture with a planted
  defect (see [`evals/README.md`](../evals/README.md#adding-a-fixture)).
  `--no-eval-fixture` skips it.

It never overwrites anything: an existing skill or fixture directory is an
error. All files are UTF-8 with LF line endings.

### A new skill is incomplete, not invalid

The skeleton passes every metadata and structure check as soon as it is
written. What it cannot pass without real content is reported honestly
rather than faked: `validate` rates the skill **incomplete** while
`TODO(author)` placeholders remain, no source is linked yet, or (in a
checkout) no eval fixture plants a defect or `docs/finding-output.md` does
not list it. An incomplete skill still fails validation (exit 1); it is just
told apart from one that breaks a rule (**invalid**).

## What `skilldeck validate` checks

```bash
skilldeck validate [NAME|PATH]... [--skills-dir PATH] [--json]
```

Give skill names from the skills directory (`--skills-dir`, by default the
checkout's `src/skilldeck/skills`), or paths to skill directories: anything
containing a slash, such as `./my-review`. With neither, every skill in the
skills directory is checked. For each skill it checks:

- `meta.yaml`, capabilities included, with the same validation that loads
  skills for `install`;
- the [bundle rules](#what-a-skill-directory-may-hold), one problem per
  offending entry (a link, a directory, an undeclared executable or any
  other file; OS and editor leftovers are ignored, as when loading);
- the `skill.md` structure, cited sources and local links, and its code
  spans against `capabilities.commands`: the rules in `skilldeck.lint`, which
  the test suite also applies to every bundled skill;
- that no `TODO(author)` placeholder is left;
- that every adapter for the skill's agents, legacy formats included, can
  render it, and that its [catalog](catalog.md) entry builds.

A skill in a checkout's `src/skilldeck/skills` also gets the repository
checks: its eval fixtures load, have `base/` and `change/` with every planted
file in `change/`, use keywords that describe each defect rather than echo
its code, keep a clean-diff fixture's tolerance small, and include a planted
one (through `evals/run_evals.py`, without running any agent); it is listed in
`docs/finding-output.md`; and the generated plugin tree and content manifests
are current (`scripts/build_plugin.py --check`, run in process). Nothing
touches the network or calls an agent.

### Trust

`validate` never runs code from the tree it checks. The eval-fixture and
generated-output checks import that checkout's own `evals/run_evals.py` and
`scripts/build_plugin.py`, so they run only when the skilldeck doing the
validating *is* that checkout's code: its `src/skilldeck` is the running
package, as with `uv run --extra dev skilldeck validate` inside it. For any
other tree that looks like a checkout (a fork, a downloaded archive, a
checkout validated by an installed skilldeck), they are skipped and the
report says to run that command inside it; the text-only
`docs/finding-output.md` check still applies. Nothing is followed through a
symlink or junction: a linked skill directory, `meta.yaml` or `skill.md` is
reported (`skill.link`) and not read, so its target's path and contents never
reach the report.

Each problem names the file (and line, where there is one), the rule and how
to fix it:

```
src/skilldeck/skills/my-review/skill.md:14: error [structure.scope] ## Scope lacks a three-dot diff against origin/<base> (/`git diff origin/<base>\.\.\.HEAD`/)
    fix: in ## Scope, determine the diff with `git fetch`, then `git diff origin/<base>...HEAD`, plus uncommitted changes and untracked files (`git ls-files --others --exclude-standard`)
```

followed by each skill's status (`ok`, `incomplete` or `invalid`) and a
summary. The exit status is 0 when there is no problem at all, 1 when there
is any, and 2 for a usage error such as an unknown skill name.

`--json` prints the same report for tools, as deterministic JSON (sorted
keys, problems sorted by skill, file, line and rule, one final newline):

```json
{
  "ok": false,
  "problems": [
    {
      "level": "incomplete",
      "line": 3,
      "message": "12 TODO(author) placeholders remain (lines 3, 4, 7, ...)",
      "path": "src/skilldeck/skills/my-review/skill.md",
      "remediation": "replace every TODO(author) placeholder with the real content",
      "rule": "content.placeholder",
      "skill": "my-review"
    }
  ],
  "schema_version": 1,
  "skills": [
    {
      "checkout": true,
      "name": "my-review",
      "path": "src/skilldeck/skills/my-review",
      "status": "incomplete"
    }
  ],
  "skipped": []
}
```

A problem that belongs to the whole checkout (a stale generated file) has
`skill: null`. `skipped` lists checks that could not apply, and why.
`schema_version` changes only if the shape changes incompatibly.

### Rules

| Rule | Level | Requires |
| --- | --- | --- |
| `meta.missing` | error | The skill directory has a `meta.yaml`. |
| `meta.encoding` | error | `meta.yaml` is UTF-8. |
| `meta.syntax` | error | `meta.yaml` is a YAML mapping. |
| `meta.missing-field` | error | `meta.yaml` has every required field. |
| `meta.unknown-field` | error | `meta.yaml` has only the known fields. |
| `meta.name` | error | `name` is 1–64 lowercase letters, digits and single hyphens. |
| `meta.name-mismatch` | error | `name` matches the skill's directory name. |
| `meta.description` | error | `description` is one non-empty line of at most 1024 characters. |
| `meta.description-period` | error | `description` is one sentence, ending with a period. |
| `meta.category` | error | `category` is a non-empty string. |
| `meta.version` | error | `version` is a `MAJOR.MINOR.PATCH` string. |
| `meta.supported-agents` | error | `supported-agents` is a non-empty list of distinct agent names. |
| `meta.unknown-agent` | error | `supported-agents` names only agents skilldeck has adapters for. |
| `meta.deprecated` | error | `deprecated`, when present, is a valid [deprecation record](#deprecating-a-skill). |
| `meta.deprecated-replacement` | error | A deprecated skill's replacement is a current skill in the same directory that supports the same agents. |
| `meta.capabilities` | error | `capabilities` follows the [capability schema](#capabilities). |
| `body.missing` | error | The skill directory has a `skill.md`. |
| `body.encoding` | error | `skill.md` is UTF-8. |
| `skill.unexpected-file` | error | The skill directory holds only `meta.yaml` and `skill.md`: no subdirectory or other file. |
| `skill.executable` | error | The skill directory holds no script or program. |
| `skill.link` | error | Neither the skill directory nor anything in it is a symlink or junction. |
| `skill.unreadable` | error | The skill directory and its entries can be read. |
| `structure.heading` | error | `skill.md` opens with a `# Title` whose words spell the skill name. |
| `structure.section` | error | `skill.md` has the `## Scope` and `## Output` sections. |
| `structure.phrase` | error | `skill.md` carries the instructions every review skill shares. |
| `structure.scope` | error | `## Scope` determines the diff the same way in every skill. |
| `structure.output` | error | `## Output` carries the shared finding-report pieces. |
| `structure.severity-rubric` | error | `## Output` inlines the shared severity rubric word for word. |
| `structure.nothing-in-scope` | error | `skill.md` says what to do when the change touches nothing in its area. |
| `structure.two-dot-range` | error | Git ranges are three-dot (`origin/<base>...HEAD`). |
| `references.cited-source` | incomplete | `skill.md` links at least one authoritative source. |
| `references.superseded` | error | `skill.md` cites no superseded edition of a standard. |
| `references.redirect-url` | error | `skill.md` links no documentation path that only survives as a redirect. |
| `references.local-link` | error | `skill.md` links only to web pages and its own headings. |
| `capabilities.undeclared-command` | error | Every command a code span in `skill.md` runs is declared in `capabilities.commands`. |
| `capabilities.unused-command` | error | Every declared command appears in `skill.md`. |
| `capabilities.network` | error | A declared `git fetch` is declared as network use of the git remote. |
| `content.placeholder` | incomplete | No `TODO(author)` placeholder remains. |
| `render.failed` | error | Every adapter for the skill's agents can render it. |
| `catalog.entry` | error | The skill's catalog entry builds. |
| `eval.fixture-missing` | incomplete | Checkout only: an eval fixture with a planted defect exercises the skill. |
| `eval.keyword-echo` | error | Checkout only: a plant's keywords describe the defect instead of echoing the planted code. |
| `eval.clean-tolerance` | error | Checkout only: a clean-diff fixture tolerates at most 2 findings. |
| `eval.fixture-invalid` | error | Checkout only: the skill's eval fixtures load, and their planted files are in `change/`. |
| `docs.finding-output` | incomplete | Checkout only: `docs/finding-output.md` lists the skill and its classifier. |
| `generated.stale` | error | Checkout only: the generated plugin tree and content manifests match the skills. |
| `generated.unchecked` | error | Checkout only: the generated-output check can run. |

## Review path

Passing `validate` is necessary, not sufficient: it proves a skill is well
formed, not that its advice is right. Nothing makes a skill official
automatically, and skilldeck generates no domain guidance of its own.

**Official skills** join the bundled catalog only through a reviewed pull
request to this repository:

1. Open an issue proposing the skill, and agree its scope and its overlap
   with existing skills.
2. Scaffold it with `skilldeck new` and write the content. Ground every
   checklist item in an authoritative source you fetched (OWASP, CIS, vendor
   documentation) and cite it in the body; don't state what no source backs.
3. Add a golden-diff eval fixture with a planted defect (ideally also a
   `-clean` one), its `SAMPLE_REPORTS` entry in
   `tests/test_eval_fixtures.py`, and run it through the evals
   ([`evals/README.md`](../evals/README.md)); record the pass rate in the pull
   request.
4. Add the skill to [`docs/finding-output.md`](finding-output.md): the list
   of review skills, the classifier table, and
   [Which skill owns what](finding-output.md#which-skill-owns-what) if it
   overlaps another skill.
5. Regenerate the plugin tree, add a `CHANGELOG.md` entry, and run
   `skilldeck validate` and the full check suite in
   [CONTRIBUTING.md](../CONTRIBUTING.md).
6. A maintainer reviews the sources, the severity anchors, the overlap with
   other skills and the eval results, and merges it or asks for changes.

**Organization-specific skills** stay in your own repository, under your own
review. Scaffold and check them with `--dir` and `--skills-dir` (see
[Organization skills](#organization-skills)); `skilldeck validate --json`
fits a CI gate. They are never added to the official catalog, however they
validate: to propose one upstream, follow the official path above.

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

Deprecating a skill also needs a `### Deprecated` entry in `CHANGELOG.md`
naming it in backticks, and CI checks for one. The skill can be removed only
after a release has published the deprecation for the notice period (90
days before 1.0). While a skill is 0.x, a breaking change bumps its minor
version. A rename is a new skill plus a deprecation of the old name.
See [Lifecycle and compatibility](lifecycle.md#deprecating-a-skill) for the
full path, including what happens to installed copies, and
[Skill versions](lifecycle.md#skill-versions) for which changes are major,
minor or patch.

### Capabilities

`capabilities` declares what the skill may ask an agent to do beyond
following its text, so a reviewer (or a user about to install it) can see
that without reading every instruction. Declare what the body actually asks
for, and update the declaration whenever the body changes what it asks:

| Key | Value | Declares |
|-----|-------|----------|
| `schema` | `1` | The capability schema. This page describes schema 1; a skilldeck that reads schema 1 rejects any other number. |
| `files` | a mapping of `read` and `write` | `read`: `none`, `diff` (the changed files) or `repo` (any file in the repository). `write`: `none`, or `repo` if the skill may edit files in the repository's working tree (as `logging` does when it adds logging). Files outside the repository are never covered, with one exception: what a declared command does by itself (below). |
| `commands` | list of commands | Commands the skill may ask the agent to run, each a program on `PATH` and its subcommand (`git diff`). An entry covers that command with the arguments the body gives it. A `<placeholder>` in angle brackets stands for a command the project defines, such as `<the project's test command>`: running it runs the repository's own code, so review it as such. A path to a file (`./check.sh`) is rejected, and so is an interpreter (`sh`, `bash`, `python`, `node`, `ruby`, `perl`, `pwsh`, ...) given a script (`sh check.sh`, `python ../x.py`) or inline code (`-c`, `-e`, `--eval`, `-Command`): a skill cannot ship scripts, and inline code would hide what runs. Declare a project-defined command as a placeholder instead. |
| `network` | list of descriptions | What the skill may contact, and why: `the git remote, via git fetch, to bring the base branch up to date`. |
| `credentials` | list of descriptions | Secrets the skill asks the agent to read (from environment variables, files or a keychain), pass on or send. A declared command that authenticates by itself with the user's existing setup, as `git fetch` uses git's credential helper and `gh` its stored login, is not listed here: declare the command and its network use instead. |
| `tools` | list of descriptions | Agent tools the skill needs beyond reading files and running its commands, such as `web fetch, to read advisory pages`. |
| `artifacts` | list of paths | Files the skill may create in the project, as POSIX paths relative to the project root (`reports/review.md`). |

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

A declared command's own side effects are covered by declaring it: `git fetch`
updates remote-tracking refs under `.git`, and `test-review`'s
`git worktree add` checks the base out into a temporary directory outside the
repository (which the skill copies the new test into and then removes with
`git worktree remove`). None of that is an edit to the repository's working
tree (`files.write`) or a file the skill leaves behind (`artifacts`), but
review a command with that in mind.

**Anything not declared is not requested.** A person reviewing a skill, or
what an agent did with it, can read the declaration as the whole of what the
skill asks for; anything more came from somewhere else. The declaration is for
review, not enforcement: skilldeck cannot sandbox the agents it installs into,
and no metadata makes a malicious instruction safe. Review the body itself
too.

Where the declaration shows up:

- **Before install**: `skilldeck show <skill> --summary` prints it with the
  skill's source, build and digest, and
  `skilldeck install <skill> --agent <agent> --dry-run` prints the same
  summary with what the install would do, writing nothing.
- **In the installed file**: every adapter appends a
  `## Declared capabilities` section to a skill that asks for more than a
  read-only review, telling the agent in plain terms everything the skill asks
  of it beyond reading files, then that it asks for nothing else. A read-only
  review reads files and runs only read-only git commands (`git fetch`,
  `git diff`, `git ls-files`, `git log`, `git show`, `git status`,
  `git blame`), which reach nothing but the git remote; it is rendered
  unchanged. Anything else brings the section: an edit (`write: repo`), a
  credential, an agent tool, an artifact, or any other command. Once the
  section is there it lists every command and every network use, the
  baseline ones included. It adds no instruction beyond the declaration.
- **For tools**: `skilldeck catalog --json` reports it as each skill's
  `capabilities` (see [the skill catalog](catalog.md)).

`skilldeck validate` checks a skill's `commands` against its body both ways
(and `tests/test_skill_structure.py` applies the same `skilldeck.lint` rule
to every bundled skill). A code span that runs a known program (common
package managers, scanners, test runners, network clients, interpreters, and
every program a skill in the same directory declares), such as
`git diff origin/<base>...HEAD`, must start with a command the skill
declares (`capabilities.undeclared-command`), and every declared command
must appear in the body (`capabilities.unused-command`); a declared
`git fetch` must come with network use of the git remote
(`capabilities.network`). A span a bundled skill only quotes, as a pattern
to look for or a command to avoid, is listed in `MENTIONED_ONLY` in
`skilldeck/lint.py`.

### What a skill directory may hold

Exactly `meta.yaml` and `skill.md`, as regular files. skilldeck installs one
file per skill, so it has no way to ship a script, a reference file or an
image, and a skill cannot declare one. The loader rejects, naming each:

- a symlink (or, on Windows, a junction), even one pointing at a file with
  the right content, and a skill directory that is itself one;
- a directory or any other file, calling it an undeclared executable when
  its suffix (`.sh`, `.py`, `.exe`, ...), execute bit (not on Windows) or
  first bytes (`#!`, or a native binary) say it is a program.

Loading ignores what an OS or editor leaves next to the files you edit, so
one stray file doesn't break every command: `.DS_Store`, `Thumbs.db`,
`desktop.ini`, `__pycache__`, and names starting `._` or `.#`, ending `~`,
of the form `#name#`, or Vim swap files (`.name.swp`, `.name.swo`, ...). A
symlink with one of those names is still rejected, except an Emacs `.#`
lock, which is one by nature. `skilldeck provenance --verify` (and so
`skilldeck catalog`), the release-integrity check, is stricter: it reports
any entry besides `meta.yaml` and `skill.md` as an unexpected file, leftovers
included, and a `meta.yaml`, `skill.md` or skill directory that is a symlink
or junction.

An execute bit on `meta.yaml` or `skill.md` themselves is ignored: skilldeck
reads them as text and never copies a file's mode, and some filesystems
(a Windows drive under WSL, for one) mark every file executable.

`skill.md` may link only to web pages (`http`, `https`, `mailto`) and to its
own headings (`#output`). A relative link, an absolute path, a `file:` URL or
any other scheme names a file the skill can't ship, so the loader rejects it
as a missing asset. It looks in Markdown links and images, reference
definitions and autolinks (`<file:///...>`), and the `src` and `href`
attributes of HTML tags; not in prose (`location.href = input`), code spans,
or fenced or indented code blocks, so examples stay possible.

## `skill.md`

The agent-neutral body of the skill — the actual instructions/prompt. Write it
without agent-specific framing (no Claude frontmatter, no Codex/Kiro path
assumptions); the adapters add whatever wrapping each agent needs at install time.

If the skill is a **review** skill that emits findings, make its `## Output`
section follow the shared [finding output format](finding-output.md) so findings
from different skills stay consistent. The structure rules in
`skilldeck.lint` (reported by `skilldeck validate`, and applied to every
bundled skill by `tests/test_skill_structure.py`) check that every review
skill carries the shared pieces, all of which the `skilldeck new` skeleton
already has:

- a `# Title` first line whose words spell the skill name (`# My Review` for
  `my-review`);
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
skilldeck validate my-skill               # every rule, offline
skilldeck list                            # should show your new skill
skilldeck show my-skill --summary         # the capabilities it declares
skilldeck show my-skill --agent claude    # the rendered file
skilldeck install my-skill --agent claude --scope project
```

Then inspect the rendered output under `.claude/skills/my-skill/SKILL.md`, and
run the skill's eval fixtures against a real agent (`evals/README.md`).
