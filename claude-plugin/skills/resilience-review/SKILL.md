---
name: resilience-review
description: Review pending changes for resilience and fault tolerance when dependencies
  fail, slow, or overload.
---

# Resilience Review

Review the **pending changes on the current branch** for resilience and fault
tolerance — how the code behaves when the things it depends on are slow, failing,
overloaded, or returning garbage. This is a reliability review, not a correctness
or security one; pair it with `logging` (so failures are observable) and
`security-review`. The patterns below draw on Michael Nygard's *Release It!*
stability patterns and the Google SRE book chapters
[Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/)
and [Handling Overload](https://sre.google/sre-book/handling-overload/).

Resilience is contextual: judge each gap by the call's blast radius and how
critical the path is. A single local call in a short-lived CLI needs little of
this; a request-path call to a remote dependency in a long-running service needs
most of it. Flag what the change actually introduces or worsens — don't demand
every pattern everywhere. These are design patterns, not libraries: apply them
with whatever the project's stack already provides rather than prescribing a
specific tool.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Review only changed files and the code paths they touch — but read the whole
   function or file around each hunk, not just the diff: a timeout, retry, or
   cleanup may sit just outside it.
3. Focus on **boundaries** — where the code crosses into something it doesn't
   control: network/RPC calls, databases, queues, caches, the filesystem,
   subprocesses, and shared or persistent state.
4. Before flagging a missing pattern, check what the stack already provides — an
   HTTP client with default timeouts, framework-level retries, or a service mesh
   may already cover the boundary.

## What to look for (by category)

### Timeouts & deadlines

- Network calls, DB queries, lock acquisitions, or subprocess waits with **no
  timeout** (or a default of "infinite") — one slow dependency hangs the caller.
- A deadline that doesn't propagate: each hop has its own generous timeout
  instead of a shrinking budget passed down the call chain.

### Retries & backoff

- Retries with **no backoff** (and no jitter) — synchronized clients hammer a
  recovering dependency (retry storm / thundering herd).
- Retrying **non-idempotent** operations without an idempotency key — duplicated
  side effects (double charge, double send) under at-least-once delivery.
- Retrying errors that won't succeed (validation/4xx, auth failures); unbounded
  retry counts; nested retries that multiply attempts at each layer.

### Failure isolation & degradation

- A flaky dependency called with no **circuit breaker / bulkhead**, so its slowness
  exhausts threads/connections and cascades into unrelated work.
- No **fallback or graceful degradation** when an *optional* dependency fails — a
  non-critical call (recommendations, enrichment) can fail the whole request.
- Wrong **fail-open vs fail-closed** choice for the context: degrade open for a
  nice-to-have, but fail closed for anything security- or correctness-critical.

### Resource management & backpressure

- Resources leaked on **error paths** — connections, file handles, locks,
  threads/tasks not released when an exception fires (missing
  `finally`/`with`/`defer`/`using`).
- **Unbounded** queues, buffers, in-memory collections, or concurrency that grow
  without limit under load (memory exhaustion).
- No **load shedding, rate limiting, or backpressure** when overloaded; connection
  pools that can be exhausted with no cap or wait timeout.

### Error handling & partial failure

- Errors **swallowed** or caught-and-ignored, hiding failures from callers and
  logs; broad catch-alls that also mask programming errors.
- **Partial failure** in a multi-step operation left in an inconsistent state — no
  rollback, compensation, or transactional boundary around related writes.
- Crashing on a **recoverable** error, or continuing past an **unrecoverable** one.

### Concurrency & shared state

- Race conditions: check-then-act or read-modify-write on shared/persistent state
  without a lock, transaction, or atomic/compare-and-swap operation.
- Assuming exactly-once where the system is at-least-once; ordering assumptions
  that concurrent execution breaks.

### Startup & shutdown

- No **graceful shutdown**: in-flight work dropped, buffers not flushed, resources
  not drained on termination signal.
- Serving traffic before dependencies are ready (readiness vs liveness not
  distinguished); no reconnect/recovery for a dropped persistent connection.

## Output

Report each finding as a single list item:

- **[severity] resilience concern** — `file:line`
  **Issue:** how the code fails when the dependency is slow, failing, or overloaded.
  **Fix:** the concrete pattern to apply (e.g. add a timeout, backoff with jitter,
  an idempotency key, a bounded queue, release on the error path).

`severity` reflects blast radius: **critical** — a routine dependency failure
hangs or cascades across the system; **high** — data loss, duplicated side
effects, or resource exhaustion under failure; **medium** — degraded behavior
confined to the failing path; **low** — hardening. The classifier is the
resilience concern (e.g. `Missing timeout`, `Retry without backoff`,
`Resource leak`, `Unbounded queue`, `No graceful degradation`). Order findings
by severity, highest first, and keep one issue per finding. For example:

- **[high] Missing timeout** — `services/enrich.py:33`
  **Issue:** `requests.get(url)` has no timeout, so a stalled enrichment service
  hangs the request thread indefinitely and can exhaust the worker pool.
  **Fix:** pass an explicit timeout (e.g. `timeout=(3, 10)`) and degrade
  gracefully — enrichment is optional for this request.

Verify before reporting: re-check each candidate against the surrounding code
and the stack's defaults, and drop any you cannot back with a concrete failure
scenario. Prefer the few findings that matter; if more than ~10 survive, report
the ones worth a human's time and summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (5 files): 2 findings, worst high.` If the change
introduces no new failure modes — or genuinely doesn't cross a failure boundary
(pure logic, local computation, docs/config) — say so explicitly rather than
manufacturing findings.
