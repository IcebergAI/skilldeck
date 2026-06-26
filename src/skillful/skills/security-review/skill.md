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

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`).
2. Review only changed files and the code paths they touch.
3. Note which ASVS categories the change actually touches — don't force findings
   in areas the diff doesn't reach.

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

Cross-cutting: **secrets** — hardcoded credentials, tokens, or keys; secrets
logged, committed, or returned in responses.

## Output

For each finding report:

- **Severity** (critical / high / medium / low)
- **ASVS category** (e.g. V8 Authorization)
- **Location** (`file:line`)
- **Description** of the vulnerability and how it could be exploited
- **Recommendation** with a concrete fix

If no security-relevant issues are found, say so explicitly rather than padding
the report. Do not flag stylistic issues — that is the job of code review.
