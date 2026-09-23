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
description: One-line summary used in `skilldeck list` and Claude frontmatter.
category: security        # free-form grouping, e.g. security, review, refactor
version: "0.1.0"
supported-agents:         # non-empty list; adapters skip skills they aren't in
  - claude
  - codex
  - kiro
```

All five fields are required, and the loader (`skilldeck.registry`) rejects a
`meta.yaml` that breaks any of these rules with an error naming the field:

| Field | Rule |
|-------|------|
| `name` | A string of 1–64 lowercase letters (`a-z`), digits and hyphens that starts and ends with a letter or digit and has no `--`, matching the directory name. |
| `description` | A non-empty, single-line string of at most 1024 characters. |
| `category` | A non-empty string. |
| `version` | A **string** of the form `MAJOR.MINOR.PATCH`: three non-negative integers without leading zeroes, e.g. `0.1.0` or `1.10.0`. |
| `supported-agents` | A non-empty list of agent names (strings), each listed once. Each must be an agent skilldeck has an adapter for. |

The `name` and `description` limits come from the
[Agent Skills specification](https://agentskills.io/specification), the
`SKILL.md` format the Claude adapter writes. The name is also used in install
paths, so the character rule keeps it a safe path component. The `version`
format is a [SemVer](https://semver.org/) normal version.

> [!IMPORTANT]
> YAML reads an unquoted `version: 1.10` as the number `1.1`, and `version: 1`
> as an integer. The loader rejects any version that isn't a string rather than
> guess what you meant, so quote any version that could be read as a number.
> Quoting every version (`version: "1.10.0"`) is simplest. A three-part version
> such as `0.1.0` is already a string in YAML, so the bundled skills leave it
> unquoted.

## `skill.md`

The agent-neutral body of the skill — the actual instructions/prompt. Write it
without agent-specific framing (no Claude frontmatter, no Codex/Kiro path
assumptions); the adapters add whatever wrapping each agent needs at install time.

If the skill is a **review** skill that emits findings, make its `## Output`
section follow the shared [finding output format](finding-output.md) so findings
from different skills stay consistent.

## Testing your skill

```bash
skilldeck list                 # should show your new skill
skilldeck install my-skill --agent claude --scope project
```

Then inspect the rendered output under `.claude/skills/my-skill/SKILL.md`.
