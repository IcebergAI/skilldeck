---
description: 'Contract fixture: a synthetic review skill that pins every adapter''s
  rendered bytes, long enough that YAML folds it onto a second line.'
agent: agent
---

# Contract demo

A synthetic skill for the adapter contract tests — it is never installed for
real. Non-ASCII text (naïve café, 検査) must reach every agent as UTF-8.

1. Run `git diff` and read the changed files.
2. Run `<the project's test command>` to see whether the change breaks a test.
3. Report each finding with its file and line.

## Declared capabilities

Beyond reading the changed files, this skill asks you to:

- run `git diff`, `<the project's test command>`

It asks for nothing else.
<!-- skilldeck name=contract-demo version=1.2.3 hash=fb4fdec5b86c601d2735353d925994bc5f477d0deb69cc3472c5bc9479caf6d5 -->
