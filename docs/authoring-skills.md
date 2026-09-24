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

All five fields are required (a sixth, `deprecated`, is optional: see
[Deprecating a skill](#deprecating-a-skill)), and the loader (`skilldeck.registry`) rejects a
`meta.yaml` that breaks any of these rules with an error naming the field:

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
past 1024 characters), and a `replacement` that is the skill itself, is not a
bundled skill, or is deprecated too. `skilldeck list` and `skilldeck catalog`
mark deprecated skills, and `skilldeck catalog --json` reports the record to
tools (see [the skill catalog](catalog.md)).

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
skilldeck install my-skill --agent claude --scope project
```

Then inspect the rendered output under `.claude/skills/my-skill/SKILL.md`.
