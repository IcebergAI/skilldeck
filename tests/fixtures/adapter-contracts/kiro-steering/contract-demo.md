---
inclusion: manual
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
<!-- skilldeck name=contract-demo version=1.2.3 hash=2fd16e9edc9ce929435f6162c3fb28d22401b6e414cdee706e24c7a8c2f1cbfe -->
