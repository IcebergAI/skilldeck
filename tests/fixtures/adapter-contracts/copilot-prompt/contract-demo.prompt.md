---
description: 'Contract fixture: a synthetic review skill that pins every adapter''s
  rendered bytes, long enough that YAML folds it onto a second line.'
agent: agent
---

# Contract demo

A synthetic skill for the adapter contract tests — it is never installed for
real. Non-ASCII text (naïve café, 検査) must reach every agent as UTF-8.

1. Run `git diff` and read the changed files.
2. Report each finding with its file and line.

## Declared capabilities

What this skill may ask for, as declared in its skilldeck metadata
(capability schema 1). The declaration is for review: nothing enforces it.
Anything not listed here is not requested by this skill.

- Files: reads the changed files; edits no files
- Commands: `git diff`
<!-- skilldeck name=contract-demo version=1.2.3 hash=502dc0d157458e666bcfd86c8e71c73b4a8a3e78dccb0f56fbfb01bbfeedbfab -->
