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
version: 0.1.0
supported-agents:         # non-empty list; adapters skip skills they aren't in
  - claude
  - codex
  - kiro
```

All five fields are required. The loader (`skilldeck.registry`) validates them and
errors clearly if anything is missing or if `name` does not match the directory.

## `skill.md`

The agent-neutral body of the skill — the actual instructions/prompt. Write it
without agent-specific framing (no Claude frontmatter, no Codex/Kiro path
assumptions); the adapters add whatever wrapping each agent needs at install time.

## Testing your skill

```bash
skilldeck list                 # should show your new skill
skilldeck install my-skill --agent claude --scope project
```

Then inspect the rendered output under `.claude/skills/my-skill/SKILL.md`.
