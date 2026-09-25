# Authoring skills

A skill is a directory named after the skill, holding two files:

```
my-review/
├── meta.yaml   # name, description, category, version, supported agents
└── skill.md    # the agent-neutral instructions
```

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
#   src/skilldeck/skills/my-review/skill.md, plant a defect in
#   evals/fixtures/my-review/ and add its SAMPLE_REPORTS entry in
#   tests/test_eval_fixtures.py, list the skill in docs/finding-output.md
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
  placeholder if omitted), `--category`, version `0.1.0`, and
  `supported-agents` listing every agent unless `--agent` names some.
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

- `meta.yaml`, with the same validation that loads skills for `install`;
- the `skill.md` structure and cited sources, the rules in `skilldeck.lint`
  that the test suite also applies to every bundled skill;
- that no `TODO(author)` placeholder is left, and that the directory holds
  nothing but the two skill files, neither of them a symlink;
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
`docs/finding-output.md` check still applies. Nothing in a skill directory is
followed through a symlink: a symlinked `meta.yaml` or `skill.md` is reported
(`skill.symlink`) and not read, so its target's path and contents never reach
the report.

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
| `body.missing` | error | The skill directory has a `skill.md`. |
| `body.encoding` | error | `skill.md` is UTF-8. |
| `skill.unexpected-file` | error | The skill directory holds only `meta.yaml` and `skill.md`. |
| `skill.symlink` | error | Nothing in the skill directory is a symlink. |
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
```

All five fields are required, and the loader (`skilldeck.registry`) rejects a
`meta.yaml` that breaks any of these rules with an error naming the field. A
sixth field, `deprecated`, is optional (see
[Deprecating a skill](#deprecating-a-skill)); any other key is an error, so a
misspelt field fails loudly instead of being ignored.

| Field | Rule |
|-------|------|
| `name` | A string of 1–64 lowercase letters (`a-z`), digits and hyphens that starts and ends with a letter or digit and has no `--`, matching the directory name. |
| `description` | A non-empty string of at most 1024 characters on a single line, with no line break of any kind (including escapes such as `"\u2028"`). |
| `category` | A non-empty string. |
| `version` | A **string** of the form `MAJOR.MINOR.PATCH`: three non-negative integers without leading zeroes, e.g. `0.1.0` or `1.10.0`. |
| `supported-agents` | A non-empty list of agent names (strings), each listed once: `claude`, `codex`, `copilot`, `cursor`, `kiro`. The legacy adapters (`copilot-prompt`, ...) follow their agent's entry and are not listed. |

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
skilldeck show my-skill --agent claude    # the rendered file, for a bundled skill
skilldeck install my-skill --agent claude --scope project
```

Then inspect the rendered output under `.claude/skills/my-skill/SKILL.md`, and
run the skill's eval fixtures against a real agent (`evals/README.md`).
