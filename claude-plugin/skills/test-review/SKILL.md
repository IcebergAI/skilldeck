---
name: test-review
description: Review pending changes for adequate, meaningful test coverage.
---

# Test Review

Review the **pending changes on the current branch** for adequate, meaningful
test coverage. Judge whether the tests prove the change works and would catch a
regression — not merely whether tests exist or coverage numbers moved. This is a
testing-quality review; pair it with `code-smells` for production-code
maintainability and `security-review` for vulnerabilities.

The checklist follows the *Tests* section of Google's code-review guide,
[What to look for in a code review](https://google.github.io/eng-practices/review/reviewer/looking-for.html)
— will the tests fail when the code is broken, without false positives when
it changes beneath them? — and *Software Engineering at Google* on
[test suites](https://abseil.io/resources/swe-book/html/ch11.html) (hermetic,
deterministic tests; coverage shows a line ran, not that it was checked),
[unit testing](https://abseil.io/resources/swe-book/html/ch12.html), and
[test doubles](https://abseil.io/resources/swe-book/html/ch13.html).

## Scope

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
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
  re-implements the code under test (loops, branches, or computed expected
  values in the test instead of obvious literals).
- **Over-mocking** — so much is stubbed the test no longer verifies real
  behavior; prefer the real implementation or a fake where practical.
- **Testing implementation, not behavior** — reaching past the public API, or
  asserting which internal calls were made rather than the resulting state;
  brittle to harmless refactors.
- **Wrong/loose assertions** — checks length but not contents, truthiness instead
  of value, or swallows the case it claims to cover.

### Reliability
- **Flaky patterns** — real time/`sleep`, network/filesystem without isolation,
  randomness without a fixed seed, order-dependent or shared mutable state
  (tests should be hermetic).
- **Slow by construction** — avoidable I/O or sleeps that belong behind fakes.

### Hygiene
- Unclear test names that don't state the behavior and expected outcome.
- Shared setup that hides the values a test's assertions depend on, or
  copy-paste that buries what each test varies — prefer descriptive (DAMP)
  over DRY in tests; giant tests asserting many unrelated behaviors.
- Skipped/`xfail`/commented-out tests added or left without justification.

## Output

Report each finding as a single list item:

- **[severity] weakness kind** — `file:line`
  **Issue:** what is untested, weak, or unreliable.
  **Fix:** the specific test or assertion to add or fix.

Rate `severity` on the shared severity rubric, impact × likelihood:
**critical** — high impact (code execution, auth bypass, stolen credentials or
bulk data, data loss, an outage), readily triggered (by anyone who can reach
it, or in routine operation); **high** — high impact behind a common
precondition (an authenticated user, a collaborator, a routine failure), or
medium impact (limited exposure, degraded service) readily triggered;
**medium** — high impact only under an unusual precondition, or medium impact
behind a common one; **low** — defense in depth and hygiene.
A test gap lets a defect ship but causes none itself, so findings here top
out at **high** — new or changed behavior with no test, a bug fix with no
regression test, or tests that would not catch a realistic regression;
**medium** — weak assertions or flaky patterns; **low** — hygiene. The
classifier is the weakness kind (e.g. `Coverage gap`, `Assertion-free test`,
`Flaky`); the location is the test or the untested production code. Order
findings by severity, highest first, and keep one issue per finding. For
example:

- **[high] Coverage gap** — `src/parser.py:57`
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
`Reviewed origin/main...HEAD (4 files): 2 findings, worst high.` If the diff
changes no behavior that needs tests (e.g. docs, comments, pure config), say
so and stop. If the tests adequately cover the change, say so explicitly
rather than inventing findings.
