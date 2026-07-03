# Logging

Add, improve, or review application logging so it is useful for security
monitoring and incident investigation without leaking sensitive data. Based on
the [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

Application-level logging captures context that infrastructure logging cannot —
who did what, to which resource, and whether it succeeded. Use this skill when
adding logging to new code, hardening existing logging, or reviewing a change
that touches logging.

## Scope

- **Writing or hardening logging**: apply the checklists below to the code you
  produce; no findings report is needed.
- **Reviewing a change**: determine the diff — `git diff <base>...HEAD` (default
  base: `main`/`master`), plus any uncommitted or untracked changes; if you are
  already on the base branch, review the uncommitted changes instead. Review the
  changed files and the code paths they touch, reading the whole function around
  each hunk (masking or sanitization may sit just outside the diff), and report
  findings as described at the end.

## Log these events

- **Authentication**: successes and failures, logout, session creation/expiry.
- **Authorization**: access-control failures, privilege changes, IDOR attempts.
- **Input/output validation**: rejected input, schema/allow-list violations.
- **Higher-risk actions**: user/role administration, sensitive-data access,
  encryption key use, data import/export, file uploads, config changes.
- **Application lifecycle**: start-up, shut-down, and logging initialization.
- **Errors and anomalies**: unhandled exceptions, deserialization failures, TLS
  failures, and suspicious business-logic events (out-of-order or limit-exceeding
  actions).
- **Consent events**: opt-ins, terms acceptance, permission grants.

## Include enough context (when / where / who / what)

- **When**: timestamp in a standard format (ISO 8601, UTC or with offset).
- **Where**: application name + version, hostname/server, module or endpoint,
  HTTP method and path.
- **Who**: a stable user identifier (e.g. user ID, not just a display name) and
  source IP / device identifier.
- **What**: event type, severity, action attempted, target resource, and result
  status (success / fail / defer) with a reason.
- Add an interaction/correlation ID so related events can be linked.
- Synchronize time across servers and devices (e.g. NTP) so timestamps are
  comparable when correlating events; record the confidence level if a source
  cannot be trusted.

## Never log these

- Passwords, session IDs or tokens, API keys, encryption keys, secrets.
- Database connection strings and other credentials.
- Payment card data and sensitive PII (health, government IDs).
- Application source code.
- Data the user has not consented to having stored, or data exceeding the log
  store's security classification.

For values that are sensitive but occasionally needed, mask, hash, or
pseudonymize rather than logging them raw (e.g. log a hashed session ID).

## Log safely

- **Prevent log injection**: neutralize CR/LF and delimiter characters in any
  user-controlled value before logging; prefer structured logging (key/value or
  JSON) so untrusted data can't forge log entries.
- **Use the framework**: log through the platform's standard logging library and
  a shared, application-wide handler — don't hand-roll `print`/`stdout` writes.
- **Choose severity deliberately**: reserve high levels for actionable events;
  don't bury security events at `debug`.
- **Fail safe**: a logging failure must not crash the request or leak internals;
  never expose stack traces to end users.
- **Don't let logging be a DoS vector**: avoid unbounded log growth and rate-limit
  attacker-controllable high-volume events.
- **Protect log integrity**: transmit logs over a secure channel, restrict who can
  read or alter them, and prefer append-only/tamper-evident storage so a record's
  modification or deletion is detectable.

## When reviewing existing logging, flag

- Secrets, tokens, or sensitive PII written to logs.
- User-controlled data logged without sanitization (log-injection risk).
- Security-relevant events that are not logged at all, or logged without the
  who/what/result context needed to investigate.
- Sensitive data returned to the client or surfaced in error responses.

Report each finding as a single list item:

- **[severity] issue kind** — `file:line`
  **Issue:** what is wrong.
  **Fix:** the concrete change that resolves it.

`severity` reflects exposure: **critical** — a secret or credential written to
logs; **high** — sensitive PII logged, or log injection from user-controlled
input; **medium** — a security event unlogged or missing the who/what/result
context needed to investigate; **low** — hygiene (format, level choice). The
classifier is the logging issue kind (e.g. `Secret in log`, `Log injection`,
`Missing event`). Order findings by severity, highest first, and keep one issue
per finding. For example:

- **[critical] Secret in log** — `auth/session.py:71`
  **Issue:** the raw bearer token is interpolated into the failure message
  (`logger.warning(f"auth failed for {token}")`), so anyone with log access can
  replay it.
  **Fix:** log a hashed or truncated token identifier and the user ID instead of
  the raw credential.

Verify before reporting: re-check each candidate against the surrounding code —
masking or sanitization may happen upstream — and drop any you cannot
substantiate. Prefer the few findings that matter; if more than ~10 survive,
report the ones worth a human's time and summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (3 files): 1 finding, critical.` If the logging is sound,
say so explicitly rather than manufacturing findings.
