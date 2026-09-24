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

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
2. Review only changed files and the code paths they touch — but read the whole
   function or file around each hunk, not just the diff: a guard or mitigation
   may sit just outside it.
3. Note which ASVS categories the change actually touches — don't force findings
   in areas the diff doesn't reach.
4. For injection findings, trace the tainted value from an attacker-controlled
   source to the sink; if you cannot identify attacker-controlled input,
   downgrade or drop the finding.
5. Companion skills own some areas: `authentication-review` V6, V7, V9, and
   V10; `logging` V16; `ci-workflow-review` pipeline config; `dependency-review`
   package manifests; `iac-review` infrastructure config;
   `llm-integration-review` LLM and agent integrations;
   `frontend-security-review` browser-side code and page headers (V3, and the
   XSS sinks, browser storage, and client-bundle secrets there; CORS and CSRF
   checks stay here). If the owner runs in
   the same review, leave its area to it; in a combined report, give each
   defect once, under the owner's classifier.

## What to look for (by ASVS category)

Numbers in parentheses are ASVS 5.0 requirement IDs
(`<chapter>.<section>.<requirement>`), for orientation — classify findings by
chapter. `L3` marks requirements only Level 3 asks for: under an L2 review,
report those only when the change gives them a concrete exploit path.

- **V1 Encoding & Sanitization** — output encoding for the right context to
  prevent XSS (HTML, URL, JavaScript/JSON; 1.2.1–1.2.3); parameterized
  SQL/NoSQL queries and OS commands (1.2.4, 1.2.5) and other interpreter
  injection (LDAP, XPath; 1.2.6, 1.2.7); no `eval()`/dynamic code execution
  (1.3.2); **SSTI** — user input used as template source rather than
  template data, or user-supplied expression-template content (1.3.7,
  1.3.5); **ReDoS** — user input in a regex unescaped (1.2.9), or a
  backtracking-prone pattern run on untrusted input (1.3.12, L3); **SSRF** —
  untrusted data used to call another service validated against an allowlist
  of protocols, domains, paths, and ports (1.3.6); **safe deserialization** —
  XML parsers with external-entity resolution off (**XXE**, 1.5.1) and no
  insecure deserializers on untrusted input (1.5.2).
- **V2 Validation & Business Logic** — input validated against an allow-list
  at a trusted service layer (2.2.1, 2.2.2); business-logic sequence, limits,
  and all-or-nothing transactions enforced server-side (2.3.1–2.3.3);
  **races** — a check-then-act on balances, stock, coupons, or bookings that
  concurrent requests can pass twice, without a lock or atomic conditional
  update (2.3.4); multi-user approval of high-value flows (2.3.5, L3);
  anti-automation and rate limiting of abusable functions (2.4.1).
- **V3 Web Frontend Security** — untrusted text rendered with safe DOM APIs,
  not as markup (DOM XSS: `textContent`, not `innerHTML`; 3.2.2); cookie
  `Secure`, `HttpOnly`, `SameSite`, and `__Host-` prefix (3.3); CSP, HSTS,
  `nosniff`, clickjacking protection via `frame-ancestors`, and CORS origin
  handling (3.4); CSRF and other cross-origin request protections (3.5);
  **open redirects** — a user-supplied return URL followed to another domain
  not on an allowlist (3.7.2).
- **V4 API & Web Service** — correct response `Content-Type` (4.1.1) and
  only intended HTTP methods (4.1.4, L3); headers set by a proxy (e.g.
  `X-Forwarded-For`) not overridable by clients (4.1.3); request smuggling
  (4.2.1) and header injection (4.2.3, 4.2.4, L3); GraphQL depth/cost
  limits and introspection off in production (4.3); WebSocket origin checks
  (4.4.2). Per-endpoint access control is V8.
- **V5 File Handling** — upload size, extension, and content validation
  (5.2.1, 5.2.2); archive size and file-count limits (5.2.3) and symlinks
  (5.2.5, L3); uploads never executed as server-side code (5.3.1); **path
  traversal** — file paths built from internal or trusted data, not
  user-submitted filenames, which also blocks LFI/RFI and SSRF through file
  paths (5.3.2); zip slip (5.3.3, L3); download filenames validated and
  encoded (5.4.1, 5.4.2).
- **V6 Authentication** — credential handling, brute-force and
  credential-stuffing defenses (6.3.1), MFA, secure recovery; no auth bypass.
- **V7 Session Management** — new session token on authentication (7.2.4),
  inactivity and absolute timeouts (7.3), sessions terminated on logout and
  account disablement, with the option to end other sessions after a factor
  change (7.4), re-authentication before sensitive account changes (7.5.1).
- **V8 Authorization** — missing or weakened function-, object- (IDOR), and
  field-level checks (8.2.1–8.2.3), enforced at a trusted service layer
  rather than trusting client claims (8.3.1), and cross-tenant isolation
  (8.4.1).
- **V9 Self-contained Tokens** — JWT/token signature verification, algorithm
  allow-list (no algorithm confusion), trusted key sources, and expiry and
  audience validation (9.1, 9.2).
- **V10 OAuth & OIDC** — correct flow, `state`/PKCE, redirect-URI exact
  matching, scope handling.
- **V11 Cryptography** — approved algorithms and modes (no ECB), authenticated
  encryption, no reused nonces/IVs (11.3); passwords stored with an approved
  password-hashing KDF (11.4.2); CSPRNG for anything non-guessable (11.5.1);
  proper key management.
- **V12 Secure Communication** — TLS enforced with no cleartext fallback
  (12.2.1, 12.3.1), certificate validation not disabled (12.3.2).
- **V13 Configuration** — backend connections authenticated with
  least-privilege, non-default credentials (13.2.1–13.2.3); outbound
  destinations allow-listed (13.2.4); secrets from a secrets manager, not
  source or config files (13.3.1); no debug modes, exposed `.git`, directory
  listings, or unintended docs/monitoring endpoints in production (13.4).
- **V14 Data Protection** — sensitive data minimized in responses
  (14.2.6, L3), kept out of URLs (14.2.1) and caches (14.2.2, 14.3.2), not
  sent to untrusted third parties (14.2.3), and protected at rest per its
  classification.
- **V15 Secure Coding & Architecture** — risky or outdated components (15.2.1)
  and dependency confusion (15.2.4, L3; see `dependency-review`); whole
  objects returned instead of the needed fields (15.3.1) and mass assignment
  (15.3.3); type juggling (15.3.5); **prototype pollution** — attacker-chosen
  keys (`__proto__`, `constructor.prototype`) merged into plain objects
  (15.3.6); HTTP parameter pollution (15.3.7); thread-safety and TOCTOU on
  shared resources such as files, deadlocks, and starvation (15.4, L3).
- **V16 Security Logging & Error Handling** — security events logged, no secrets
  or sensitive data in logs, no stack traces or internal detail leaked to users.
- **V17 WebRTC** — only if the change touches WebRTC: TURN/STUN server abuse,
  signalling authentication, SDP and ICE handling, media-channel confidentiality.

Cross-cutting: **secrets** — hardcoded credentials, tokens, or keys; secrets
logged, committed, or returned in responses. **LLM integrations** (prompt
injection, model output reaching tools or sinks) have no ASVS 5.0 chapter;
review them with `llm-integration-review`.

## Output

Report each finding as a single list item:

- **[severity] ASVS category** — `file:line`
  **Issue:** the vulnerability and how it could be exploited.
  **Fix:** the concrete change that resolves it.

Rate `severity` on the shared severity rubric, impact × likelihood:
**critical** — high impact (code execution, auth bypass, stolen credentials or
bulk data, data loss, an outage), readily triggered (by anyone who can reach
it, or in routine operation); **high** — high impact behind a common
precondition (an authenticated user, a collaborator, a routine failure), or
medium impact (limited exposure, degraded service) readily triggered;
**medium** — high impact only under an unusual precondition, medium impact
behind a common one, or low impact readily triggered (a weakened defense
anyone can reach); **low** — medium impact only under an unusual
precondition, or low impact behind any precondition (most defense in depth
and hygiene).
Here, a live credential committed to the repository or written to logs others
can read is always **critical**, and its Fix must also
[revoke and rotate](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
it. The classifier is the ASVS category (e.g. `V8 Authorization`;
`V13 Configuration` for secrets in code). Order findings by severity, highest
first, and keep one issue per finding. For example:

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
`Reviewed origin/main...HEAD (4 files): 2 findings, worst high.` If the diff
touches nothing security-relevant (e.g. docs or comments only, once you have
checked them for pasted credentials), say so and stop. If no
security-relevant issues are found, say the change is clean
explicitly rather than padding the report. Do not flag stylistic issues — that
is the job of code review.
