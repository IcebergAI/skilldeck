# Code Smells

Review the **pending changes on the current branch** for code smells — surface
indicators that the code may need refactoring. This is a maintainability review,
not a security or correctness review; pair it with `security-review` for the
former. Categories follow the
[refactoring.guru code smells catalog](https://refactoring.guru/refactoring/smells).

A smell is a hint, not a guaranteed defect. Judge each in context, prefer the
smells the diff actually introduces or worsens, and don't flag a smell the change
merely inherited from surrounding code.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`).
2. Review only changed files and the code paths they touch.

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

`severity` is one of **critical / high / medium / low** and reflects how much the
smell hurts maintainability and how worth fixing it is now. The classifier is the
smell and its group (e.g. `Long Method (Bloaters)`). Order findings by severity,
highest first, and keep one smell per finding.

Not every smell is worth fixing now — prioritize. If the change is clean, say so
rather than manufacturing findings.
