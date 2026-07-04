---
name: migration-review
description: Review database schema and data migrations for safety under a live, rolling
  deploy.
---

# Migration Review

Review the **pending changes on the current branch** that add or alter database
schema or run data migrations, for safety under a **live, rolling deploy**. This
is a reliability review focused on the deploy window, not general SQL correctness;
pair it with `resilience-review` and `security-review`. It builds on the
expand/contract (parallel change) pattern and engineering guidance such as
GitLab's
[Avoiding downtime in migrations](https://docs.gitlab.com/development/database/avoiding_downtime_in_migrations/).

The core risk: during a rolling deploy the **old and new application code run
against the same schema at once**, and the migration executes against a live,
possibly large table. A migration is safe only when it (a) keeps the currently
deployed code working until that code is gone, (b) doesn't hold long locks on a
hot table, and (c) can be undone without losing data.

Migration safety is contextual: a tiny table, a greenfield app, or a
maintenance-window deploy relaxes most of this. Judge by **table size, traffic,
and deploy model** — don't demand a concurrent index build on a ten-row config
table. Flag what the change introduces; note the target engine and version where
behavior differs (Postgres / MySQL / SQLite lock and rewrite differently).

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Review the migration files / schema definitions in the diff (migration
   directories, `*.sql`, ORM migrations, `schema.rb`/`structure.sql`, Alembic,
   Prisma, Knex, etc.) **and** the application code that reads or writes the
   columns and tables they change.
3. Determine whether old code must keep working while the migration runs — if the
   deploy is rolling or multi-instance, it must.
4. Note migration-safety tooling the project already runs (e.g.
   `strong_migrations`, `squawk`, safety-assured annotations) — don't re-flag
   what it already enforces; focus on what it can't see.

## What to look for (by category)

### Backward compatibility (expand/contract)

- **Dropping or renaming** a column or table the currently deployed code still
  reads or writes — breaks the moment the migration lands, before new code is out.
  Split into expand → backfill → deploy → contract across releases.
- Renaming in a single step (no engine makes a rename transparent to running code).
- A new **`NOT NULL` column with no default** while old code still inserts rows
  that omit it; or narrowing a type / tightening a constraint old code can violate.

### Locking & blocking operations

- Building an index **non-concurrently** — blocks writes on the table for the
  build's duration.
- Adding a column with a **volatile or computed default** that forces a full table
  rewrite under an exclusive lock (engine/version dependent).
- `ALTER COLUMN` type changes that rewrite the table; `SET NOT NULL` on an existing
  column (full scan under lock — prefer a `NOT VALID` check constraint then
  `VALIDATE`, where supported).
- Adding a **foreign key** that validates existing rows synchronously and locks
  both tables.
- No `lock_timeout` / `statement_timeout` — a migration that can't get its lock
  queues behind and then blocks all traffic on the table.

### Backfills & data migrations

- Backfilling a large table in a **single statement / transaction** — long locks,
  long-held transaction, replication lag.
- **Mixing DDL and DML** (schema change and data backfill) in one migration or
  transaction.
- Backfill that isn't **batched, idempotent, or resumable**, or that assumes it
  finishes within a transaction or the deploy window.

### Constraints & integrity

- Unique / check / FK constraints added without first validating existing data, or
  added in a way that locks; a constraint existing rows already violate (the
  migration fails partway).
- Dropping an index or constraint a query or feature still depends on.

### Reversibility & data safety

- **Destructive** operations (`DROP COLUMN`/`TABLE`, `TRUNCATE`, lossy type
  changes) with no backup/export and no recovery path.
- Irreversible migration with no `down`/rollback, or a `down` that silently loses
  data or doesn't actually restore the prior state.

### Sequencing & transactionality

- A migration that must run strictly before or after the code that needs it, but
  whose ordering relative to the rollout isn't guaranteed.
- A long-running migration sitting in the deploy's critical path, blocking the
  rollout.
- Assuming **transactional DDL** where the engine doesn't provide it (e.g. MySQL
  auto-commits DDL) — a failure can leave the schema half-applied.

## Output

Report each finding as a single list item:

- **[severity] migration hazard** — `file:line`
  **Issue:** what breaks or blocks, and under what conditions (deploy model, table
  size, lock held).
  **Fix:** the safe alternative (e.g. expand/contract across releases, build the
  index concurrently, batch the backfill, add the constraint `NOT VALID` then
  validate, set a lock timeout).

`severity` reflects deploy-window risk: **critical** — breaks the currently
deployed code, or locks a hot table for the duration of a long operation;
**high** — likely to block or fail under production load, or to leave the schema
half-applied; **medium** — risky only under specific conditions (table growth,
deploy timing); **low** — reversibility and hygiene. The classifier is the
migration hazard (e.g. `Backward-incompatible change`, `Blocking lock`,
`Unbatched backfill`, `Irreversible`). Order findings by severity, highest
first, and keep one issue per finding. For example:

- **[critical] Blocking lock** — `db/migrate/20260703_add_index_to_events.rb:5`
  **Issue:** `add_index :events, :account_id` builds non-concurrently; on a
  large, write-hot `events` table this blocks all writes for the duration of the
  build.
  **Fix:** build concurrently (`algorithm: :concurrently`, outside a
  transaction) and set a `lock_timeout`.

Verify before reporting: confirm each hazard against the engine's actual
behavior for the stated version and the table's realistic size, and drop any you
cannot tie to a concrete deploy-window failure. Prefer the few findings that
matter; if more than ~10 survive, report the ones worth a human's time and
summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (2 migrations): 1 finding, critical.` If the diff contains
no schema or data migration, say so rather than reviewing application code. If
the migrations are safe for the project's deploy model, say so explicitly rather
than manufacturing findings.
