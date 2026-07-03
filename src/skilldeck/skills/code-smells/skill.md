# Code Smells

Review the **pending changes on the current branch** for code smells — surface
indicators that the code may need refactoring. This is a maintainability review,
not a security or correctness review; pair it with `security-review` for the
former. Categories follow the
[refactoring.guru code smells catalog](https://refactoring.guru/refactoring/smells).

A smell is a hint, not a guaranteed defect. Judge each in context, prefer the
smells the diff actually introduces or worsens, and don't flag a smell the change
merely inherited from surrounding code.

Judge against the language's idiom, not the catalog's original OO context: a
Python dataclass or Go struct is not a *Data Class* smell, pattern matching in
Rust or an ML-family language is not a *Switch Statements* smell, and doc
comments are not a *Comments* smell.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Review only changed files and the code paths they touch — but read the whole
   function or class around each hunk, not just the diff, so you judge the
   construct in its real context.

## What to look for (by category)

### Bloaters — code grown too large to work with

- **Long Method** — a method doing too much; hard to read or name succinctly.
- **Large Class** — a class with too many responsibilities or fields.
- **Primitive Obsession** — primitives/strings where a small type or value object
  belongs (e.g. raw strings for money, units, or IDs).
- **Long Parameter List** — many parameters that should be grouped into an object.
- **Data Clumps** — the same group of variables passed around together repeatedly.

### Object-Orientation Abusers — OO principles applied incompletely

- **Switch Statements** — type-branching conditionals that polymorphism would
  replace, especially when duplicated across the codebase.
- **Temporary Field** — fields only set in certain circumstances, otherwise empty.
- **Refused Bequest** — a subclass that ignores most of what it inherits.
- **Alternative Classes with Different Interfaces** — classes doing the same job
  with inconsistent method names/signatures.

### Change Preventers — one change forces many others

- **Divergent Change** — one class changed for many unrelated reasons.
- **Shotgun Surgery** — one conceptual change requires edits scattered across many
  classes/files.
- **Parallel Inheritance Hierarchies** — adding a subclass forces a matching
  subclass in another hierarchy.

### Dispensables — things whose removal makes code cleaner

- **Duplicate Code** — identical or near-identical logic in multiple places.
- **Dead Code** — unused variables, parameters, methods, or branches.
- **Lazy Class** — a class that no longer earns its keep.
- **Speculative Generality** — abstraction/hooks added for needs that don't exist.
- **Data Class** — a class that is only fields with no behavior.
- **Comments** — comments compensating for unclear code that should be rewritten.

### Couplers — excessive coupling or delegation

- **Feature Envy** — a method more interested in another class's data than its own.
- **Inappropriate Intimacy** — classes reaching into each other's internals.
- **Message Chains** — long `a.b().c().d()` navigation chains.
- **Middle Man** — a class that only delegates to another and adds nothing.
- **Incomplete Library Class** — a library that lacks a needed method, worked
  around with awkward client-side code instead of an introduced/wrapper method.

## Output

Report each finding as a single list item:

- **[severity] Smell (Category)** — `file:line`
  **Issue:** the concrete maintainability cost in this code.
  **Fix:** the refactoring that addresses it (e.g. Extract Method, Introduce
  Parameter Object, Replace Conditional with Polymorphism).

`severity` reflects maintainability cost now: **critical** — actively misleading
or already forcing error-prone duplicate edits; **high** — will make the next
change to this code noticeably harder; **medium** — worth fixing when this code
is next touched; **low** — cosmetic. The classifier is the smell and its group
(e.g. `Long Method (Bloaters)`). Order findings by severity, highest first, and
keep one smell per finding. For example:

- **[medium] Long Method (Bloaters)** — `billing/invoice.py:42`
  **Issue:** `generate_invoice` is ~120 lines mixing tax lookup, discount rules,
  and PDF rendering, so each concern changes for a different reason and none can
  be tested alone.
  **Fix:** Extract Method — pull out `calculate_tax`, `apply_discounts`, and
  `render_pdf`, leaving `generate_invoice` to orchestrate.

Verify before reporting: re-check each candidate against the surrounding code
and drop any you cannot tie to a concrete maintainability cost. Not every smell
is worth fixing now — prefer the few that matter; if more than ~10 survive,
report the ones worth a human's time and summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (4 files): 3 findings, worst high.` If the change is clean,
say so rather than manufacturing findings.
