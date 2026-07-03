# Test Review

Review the **pending changes on the current branch** for adequate, meaningful
test coverage. Judge whether the tests prove the change works and would catch a
regression — not merely whether tests exist or coverage numbers moved. This is a
testing-quality review; pair it with `code-smells` for production-code
maintainability and `security-review` for vulnerabilities.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Map changed production code to the tests that exercise it. Note new or
   changed behavior that has **no** corresponding test. Search the whole test
   suite, not just the diff — coverage may live in tests the change didn't touch.
3. Match the project's existing test conventions (framework, layout, naming);
   judge against them rather than imposing a different style.
4. For a bug fix, confirm the regression test would actually fail without the
   fix — read the pre-change code (or run the test against it if cheap) rather
   than assuming.

## What to look for

### Coverage gaps
- New functions, branches, or error paths with no test exercising them.
- Bug fixes with no regression test that fails without the fix.
- Changed behavior where existing tests were not updated to match.
- Boundary and edge cases: empty/null, zero/negative, max/overflow, off-by-one,
  unicode, timezones, concurrency.
- Error and failure paths, not just the happy path.

### Weak or misleading tests
- **Assertion-free tests** — exercises code but asserts nothing (or only that it
  "doesn't throw").
- **Tautological / trivial** — asserts a mock returns what it was told to, or
  re-implements the code under test.
- **Over-mocking** — so much is stubbed the test no longer verifies real behavior.
- **Testing implementation, not behavior** — brittle to harmless refactors.
- **Wrong/loose assertions** — checks length but not contents, truthiness instead
  of value, or swallows the case it claims to cover.

### Reliability
- **Flaky patterns** — real time/`sleep`, network/filesystem without isolation,
  randomness without a fixed seed, order-dependent or shared mutable state.
- **Slow by construction** — avoidable I/O or sleeps that belong behind fakes.

### Hygiene
- Unclear test names that don't state the scenario and expected outcome.
- Duplicated setup that should be a fixture/helper; giant tests asserting many
  unrelated things.
- Skipped/`xfail`/commented-out tests added or left without justification.

## Output

Report each finding as a single list item:

- **[severity] weakness kind** — `file:line`
  **Issue:** what is untested, weak, or unreliable.
  **Fix:** the specific test or assertion to add or fix.

`severity` reflects regression risk: **critical** — new or changed behavior with
no test at all, or a bug fix with no regression test; **high** — tests exist but
would not catch a realistic regression; **medium** — weak assertions or flaky
patterns; **low** — hygiene. The classifier is the weakness kind (e.g.
`Coverage gap`, `Assertion-free test`, `Flaky`); the location is the test or the
untested production code. Order findings by severity, highest first, and keep
one issue per finding. For example:

- **[critical] Coverage gap** — `src/parser.py:57`
  **Issue:** the new `strict=True` branch that raises `ParseError` has no test;
  a regression that silently accepts malformed input would not be caught.
  **Fix:** add a test that passes malformed input with `strict=True` and asserts
  `ParseError` is raised.

Verify before reporting: re-check each candidate — search the suite for existing
coverage before calling something untested — and drop any you cannot back with a
realistic missed regression. Prefer the few findings that matter; if more than
~10 survive, report the ones worth a human's time and summarize the rest in a
line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (4 files): 2 findings, worst critical.` If the tests
adequately cover the change, say so explicitly rather than inventing findings.
If the diff genuinely needs no tests (e.g. docs, comments, pure config), state
that instead of forcing suggestions.
