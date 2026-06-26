# Test Review

Review the **pending changes on the current branch** for adequate, meaningful
test coverage. Judge whether the tests prove the change works and would catch a
regression — not merely whether tests exist or coverage numbers moved. This is a
testing-quality review; pair it with `code-smells` for production-code
maintainability and `security-review` for vulnerabilities.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`).
2. Map changed production code to the tests that exercise it. Note new or
   changed behavior that has **no** corresponding test.
3. Match the project's existing test conventions (framework, layout, naming);
   judge against them rather than imposing a different style.

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

For each finding report:

- **Severity** (critical / high / medium / low) — weight untested behavior and
  fixes-without-regression-tests highest.
- **Location** (`file:line`) — the test, or the untested production code.
- **Issue** — what is untested, weak, or unreliable.
- **Recommendation** — the specific test or assertion to add or fix.

If the tests adequately cover the change, say so explicitly rather than inventing
findings. If the diff is production code that genuinely needs no tests (e.g. docs,
comments, pure config), state that instead of forcing suggestions.
