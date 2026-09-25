---
inclusion: manual
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
<!-- skilldeck name=contract-demo version=1.2.3 hash=fe0aa47ce7ebec261fc4156aab2a69e7d96daeb153d57803ac0735134c5bf705 -->
