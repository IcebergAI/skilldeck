# Security Review

Perform a security review of the **pending changes on the current branch** (the
diff against the base branch), not the entire codebase. Focus on vulnerabilities
that the change introduces or exposes.

The review checklist is organized around the
[OWASP Application Security Verification Standard (ASVS) 5.0](https://owasp.org/www-project-application-security-verification-standard/).
ASVS defines three assurance levels — **L1** (baseline), **L2** (the recommended
default for most applications), and **L3** (high-value or critical applications).
Unless told otherwise, review to **L2**.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Review only changed files and the code paths they touch — but read the whole
   function or file around each hunk, not just the diff: a guard or mitigation
   may sit just outside it.
3. Note which ASVS categories the change actually touches — don't force findings
   in areas the diff doesn't reach.
4. For injection findings, trace the tainted value from an attacker-controlled
   source to the sink; if you cannot identify attacker-controlled input,
   downgrade or drop the finding.

## What to look for (by ASVS category)

- **V1 Encoding & Sanitization** — output encoding for the right context (HTML,
  JS, SQL, OS command, LDAP); injection from untrusted input; path traversal.
- **V2 Validation & Business Logic** — input validated against an allow-list;
  business-logic limits, sequencing, and anti-automation enforced server-side.
- **V3 Web Frontend Security** — XSS, CSP, clickjacking, CSRF protections,
  unsafe handling of untrusted content in the browser.
- **V4 API & Web Service** — REST/GraphQL authz per endpoint, mass assignment,
  content-type and method enforcement, rate limiting.
- **V5 File Handling** — upload validation, type/size limits, safe storage paths,
  SSRF via file/URL fetches, deserialization of untrusted data.
- **V6 Authentication** — credential handling, password storage, MFA, secure
  recovery and lockout; no auth bypass.
- **V7 Session Management** — secure session creation, rotation on privilege
  change, timeout, secure/HttpOnly cookies, invalidation on logout.
- **V8 Authorization** — missing or weakened access checks, privilege escalation,
  IDOR; enforce least privilege server-side, never trust client claims.
- **V9 Self-contained Tokens** — JWT/token signature verification, algorithm
  confusion, expiry and audience/issuer validation.
- **V10 OAuth & OIDC** — correct flow, state/PKCE, redirect-URI validation,
  scope handling.
- **V11 Cryptography** — strong algorithms, no static IVs/salts, authenticated
  encryption, secure (CSPRNG) randomness, proper key management.
- **V12 Secure Communication** — TLS enforced, certificate validation not
  disabled, no cleartext transport of sensitive data.
- **V13 Configuration** — secure defaults, no debug/verbose modes in prod,
  hardened headers, dependency and secrets configuration.
- **V14 Data Protection** — sensitive data minimized, encrypted at rest where
  required, not exposed in responses, caches, or URLs.
- **V15 Secure Coding & Architecture** — unsafe deserialization, dangerous
  language/runtime features, risky newly-added dependencies with known CVEs.
- **V16 Security Logging & Error Handling** — security events logged, no secrets
  or sensitive data in logs, no stack traces or internal detail leaked to users.
  (See the `logging` skill for depth.)
- **V17 WebRTC** — only if the change touches WebRTC: TURN/STUN server abuse,
  signalling authentication, SDP and ICE handling, media-channel confidentiality.

Cross-cutting: **secrets** — hardcoded credentials, tokens, or keys; secrets
logged, committed, or returned in responses.

## Output

Report each finding as a single list item:

- **[severity] ASVS category** — `file:line`
  **Issue:** the vulnerability and how it could be exploited.
  **Fix:** the concrete change that resolves it.

`severity` reflects exploitability and impact: **critical** — exploitable by an
unauthenticated attacker, or direct compromise of data or accounts; **high** —
exploitable by an authenticated user or behind a common precondition;
**medium** — limited impact or unusual preconditions; **low** — defense-in-depth
hardening. The classifier is the ASVS category (e.g. `V8 Authorization`). Order
findings by severity, highest first, and keep one issue per finding. For example:

- **[high] V8 Authorization** — `api/orders.py:88`
  **Issue:** `GET /orders/<id>` loads the order by ID without checking it
  belongs to the requesting user, so any authenticated user can read any order
  (IDOR).
  **Fix:** scope the query to the owner
  (`Order.get(id, user_id=current_user.id)`) and return 404 on a miss.

Verify before reporting: re-check each candidate against the surrounding code,
quote the offending line in the Issue, and drop anything you cannot back with a
concrete exploit path. Prefer the few findings that matter — if more than ~10
survive, report the ones worth a human's time and summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (4 files): 2 findings, worst high.` If no security-relevant
issues are found, say the change is clean explicitly rather than padding the
report. Do not flag stylistic issues — that is the job of code review.
