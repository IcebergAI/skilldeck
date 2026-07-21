---
name: authentication-review
description: Review authentication changes — passwords, MFA, sessions, tokens, OAuth/OIDC,
  SAML, and LDAP sign-in — for login-bypass and account-takeover defects, aligned
  to OWASP ASVS 5.0.
---

# Authentication Review

Review the **pending changes on the current branch** that touch authentication —
login and credential handling, MFA, sessions and cookies, JWTs and API tokens,
OAuth 2.0/OIDC, SAML, and LDAP-backed sign-in — for login bypass and account
takeover. Findings are classified against the
[OWASP Application Security Verification Standard (ASVS) 5.0](https://owasp.org/www-project-application-security-verification-standard/)
(chiefly V6 Authentication, V7 Session Management, V9 Self-contained Tokens,
and V10 OAuth & OIDC). The concrete patterns come from
[RFC 9700 (OAuth 2.0 Security Best Current Practice)](https://www.rfc-editor.org/rfc/rfc9700),
[NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html), and the
OWASP [Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html),
[Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[Multifactor Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html),
[Forgot Password](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html), and
[SAML Security](https://cheatsheetseries.owasp.org/cheatsheets/SAML_Security_Cheat_Sheet.html)
cheat sheets. Pair with `security-review` for breadth across the other ASVS
categories — it covers authentication at one-bullet depth; this skill goes deep
on that slice.

The worst authentication bugs are **absent verification**: a signature that is
never checked, a bind that succeeds on an empty password, a `state` value that
is generated but never compared. Absence looks like clean code in a diff, so
review against what *must* happen in each flow, not just what the changed lines
do. Exploitability hinges on **who can reach the code path before
authenticating** and **what a forged identity yields** — establish both before
judging severity.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Route diff signals to the sections below; a change rarely touches all of
   them:
   - **Passwords & recovery** — login/registration/reset/recovery routes;
     hashing calls (`argon2`, `bcrypt`, `scrypt`, `pbkdf2`, `hashlib`,
     `passlib`); user models with password or secret columns.
   - **MFA** — TOTP/OTP/WebAuthn verification, enrollment, backup codes,
     step-up or "remember this device" logic.
   - **Sessions & cookies** — `Set-Cookie`, session middleware or config
     (`express-session`, `SESSION_COOKIE_*`), login/logout handlers,
     remember-me.
   - **JWTs & API tokens** — `jwt`/`jose`/`PyJWT`/`jsonwebtoken` imports, token
     issue/verify code, `Authorization: Bearer` parsing, API-key checks.
   - **OAuth/OIDC** — `redirect_uri`, `state`, `nonce`, `code_challenge`,
     `id_token`; authorize/token/callback endpoints; `authlib`, `oauthlib`,
     `passport`, `omniauth`, `spring-security-oauth2`.
   - **SAML** — `SAMLResponse`, ACS endpoints, `xmlsec`, `python3-saml`,
     `ruby-saml`, `passport-saml`, IdP metadata XML.
   - **LDAP** — `ldap3`, `python-ldap`, `DirContext`, `ldap://` URLs, `bind()`
     calls used for sign-in.
3. Read the whole flow around each hunk, not just the diff — the framework or
   library may already enforce a control (`authlib` validates `state` and
   `nonce`; many session middlewares rotate IDs on regenerate), and a guard may
   sit just outside the changed lines. Only report a missing control after
   confirming nothing else provides it.
4. Apply only the sections the diff actually touches — don't force findings in
   protocols the change doesn't reach.

## What to look for (by area)

### Passwords, credentials & recovery (V6.2–V6.4, V11.4)

- Password storage uses an approved, computationally intensive KDF with
  current-guidance parameters — Argon2id (≥19 MiB, t=2, p=1), scrypt (N=2^17,
  r=8, p=1), bcrypt (work factor ≥10), or PBKDF2-HMAC-SHA256 (≥600,000
  iterations) — never a fast hash (MD5/SHA-*) or reversible encryption, and
  with a unique per-password salt (library-managed, not hand-rolled).
- bcrypt truncates input at 72 bytes: enforce a matching maximum, and treat
  pre-hashing (`bcrypt(sha(password))`) as a finding — raw digests containing
  null bytes truncate the input.
- Password policy per NIST SP 800-63B: minimum 8 characters (15 when passwords
  are the only factor), at least 64 allowed, all characters permitted, **no
  composition rules, no periodic rotation**, candidates screened against a
  breached/common-password blocklist; input verified exactly as received (no
  truncation or case-folding).
- User enumeration: login, registration, and reset must return the same
  message, status code, and response time whether or not the account exists —
  no quick-exit path that skips the hash computation for unknown users.
- Secrets and tokens compared in constant time (`hmac.compare_digest`,
  `crypto.timingSafeEqual`), never `==`.
- Brute-force controls on login and OTP verification: rate limiting or lockout
  tied to the account (not just source IP); a reset *request* must not lock the
  account (denial-of-service on a known username).
- Reset tokens: CSPRNG-generated, single-use, short-lived, bound to the
  account, stored hashed; the reset URL never built from the request `Host`
  header; completing a reset does not auto-login, must not bypass enabled MFA,
  and invalidates outstanding reset tokens and (at least optionally) other
  active sessions.
- Password change requires the current password; no default (`admin`/`root`),
  hardcoded, or debug-bypass credentials; no security questions or password
  hints.

### Multi-factor authentication (V6.5–V6.6)

- The second factor is enforced server-side and cannot be skipped: check for
  direct navigation past the MFA step, a replayed post-MFA request, or a
  client-supplied flag/step-state that marks MFA as passed. Every login
  surface — web, API, mobile — must enforce it, not just the primary form.
- Recovery and reset flows must not silently bypass or disable MFA; changing
  or removing a factor requires re-authentication with an existing factor and
  triggers an out-of-band notification.
- OTPs: single-use, short-lived (TOTP ~30s; out-of-band codes ≤10 minutes),
  CSPRNG-generated, strict attempt limits, never logged, and bound to the
  authentication request that produced them (no replay across attempts).
- Backup codes are single-use and stored hashed like passwords.
- "Remember this device" tokens are scoped, expiring, and revocable — not a
  permanent cookie that skips MFA forever.
- SMS/voice codes are a restricted authenticator under SP 800-63B — flag new
  SMS-only MFA for high-value applications.

### Sessions & cookies (V7, V3.3)

- A **new session token on every authentication** and privilege change, with
  the old token terminated (session fixation); password change offers to
  terminate other active sessions; sessions terminated when an account is
  disabled.
- Logout invalidates the session server-side — check the store/invalidate
  call, not the cookie deletion or redirect. Self-contained session tokens
  need a real termination story (denylist, per-user cutoff, or key rotation).
- Session cookies: `Secure`, `HttpOnly`, `SameSite=Strict` or `Lax` (never an
  unset default), the `__Host-` prefix unless cross-host sharing is intended,
  `Domain` unset and `Path` tight.
- Session IDs from the framework's CSPRNG mechanism (≥128 bits), not
  hand-rolled; carried only in cookies — never URLs or logs; the app must not
  accept a session ID it never issued (strict acceptance).
- Idle and absolute timeouts enforced server-side.
- Full re-authentication (or step-up) before modifying attributes that affect
  authentication or recovery — email, phone, MFA configuration.
- Client-side (signed-cookie) sessions: contents are readable — no secrets
  inside; a weak, defaulted, or committed signing key makes the session
  forgeable. No session tokens or JWTs in `localStorage`.

### JWTs & API tokens (V9)

- The signature or MAC is actually verified before any claim is trusted, with
  a pinned algorithm allow-list — no `none`, no accepting both HS* and RS* for
  the same context (key-confusion: an RSA public key used as an HMAC secret).
  Flag `jwt.decode(...)` with verification disabled or no `algorithms=` pin.
- Verification keys come from pre-configured trusted sources: `jku`, `x5u`,
  `jwk`, and `kid` headers must never select attacker-controlled keys — watch
  `kid` flowing into file paths or SQL.
- `exp`/`nbf` enforced; `aud` validated against this service; token type and
  purpose checked — an ID token is not an access token; user identity derived
  from `iss`+`sub`, not a reassignable claim like email.
- Signing secrets: not weak, hardcoded, or committed; not the same symmetric
  key shared across services or audiences.
- Long-lived tokens have a revocation story (rotation, denylist, absolute
  refresh expiry) — logout that cannot revoke is a finding.
- Tokens never in query strings, `Referer`, or logs; API keys stored hashed
  and compared constant-time; no static API keys used as session tokens.

### OAuth 2.0 (V10, RFC 9700)

- Authorization code flow with **PKCE (S256)** — mandatory for public clients,
  recommended for confidential ones; `code_challenge_method=plain` rejected.
- Callback CSRF: a per-transaction `state` (or PKCE/`nonce` serving the same
  role) bound to the user-agent session, unguessable, and **actually validated
  on the callback** — generation without comparison is the classic defect.
- `redirect_uri` validated against a pre-registered allow-list by **exact
  string match** — no prefix, wildcard, or subdomain matching, and no open
  redirector reachable from a registered URI.
- Authorization codes single-use (a second redemption revokes the tokens
  already issued) and short-lived (≤10 minutes).
- Deprecated grants introduced: implicit (`response_type=token`) and resource
  owner password credentials must not be used.
- Tokens only where needed: with a backend-for-frontend, browser JavaScript
  never holds access/refresh tokens; client secrets never shipped in frontend
  or mobile code; token requests from confidential clients are authenticated.
- Refresh tokens sender-constrained or rotated with revoke-on-replay, with an
  absolute expiry; scopes requested minimally and not silently escalated on
  refresh.
- Multiple authorization servers configured → mix-up defense: validate the
  `iss` parameter on the authorization response.

### OIDC (V10.5)

- Full ID token validation: signature against the issuer's JWKS, `iss`, `aud`
  equals the `client_id`, `exp` — and the `nonce` claim matched against the
  value sent in the authentication request (replay).
- Account identity keyed on `iss`+`sub` — never on email; with multiple IdPs,
  the same user identifier from a different IdP must not resolve to the same
  account (IdP-spoofing); `email_verified` checked before any email-based
  account linking (pre-auth account takeover).
- Discovery metadata and JWKS fetched over TLS from the **pre-configured**
  issuer, never from an issuer claim inside the not-yet-verified token;
  metadata whose issuer URL differs from the configured one rejected.
- ID tokens not accepted as API credentials at resource servers; `acr`/`amr`/
  `auth_time` verified when the app requires a particular authentication
  strength or recency.

### SAML sign-in (V6.8)

- Signature **presence and integrity** validated on the element actually being
  trusted: an unsigned Assertion inside a signed Response envelope (or a
  `ds:Reference` that doesn't cover the assertion) means identity claims are
  attacker-writable. Reject unsigned assertions and SHA-1 signature/digest
  algorithms.
- XML Signature Wrapping: schema-validate the document first, then read
  identity data **only from the signed node the library returned** — never
  re-query the raw document (`getElementsByTagName`) after verification.
  Verification keys come from locally configured IdP metadata; `KeyInfo`
  embedded in the response is ignored.
- Hand-rolled parsing of `SAMLResponse` is itself a finding — and the parser
  must have DTDs/external entities disabled (XXE).
- Replay and context: assertions processed only once within their validity
  window; `InResponseTo` matched to the outstanding `AuthnRequest`;
  `NotBefore`/`NotOnOrAfter`, `AudienceRestriction` (the SP's EntityID),
  `SubjectConfirmationData` `Recipient`, and `Destination` (the exact ACS URL)
  all validated.
- `RelayState` used as a URL is allow-listed (open redirect); IdP-initiated
  SSO disallowed or given dedicated replay/validation handling.

### LDAP sign-in (V6.2)

- Empty or whitespace passwords rejected **before** the bind: most directories
  treat an empty-password simple bind as anonymous/unauthenticated and return
  success, so `bind(user_dn, "")` logs anyone in.
- The bind *result* is checked — `ldap3`'s `bind()` returns `False` rather
  than raising, so an unchecked call authenticates everyone.
- Search-then-bind: locate the user's DN with a least-privilege service
  account, then bind as the user — never password comparison inside a search
  filter; escape user input used in the lookup filter/DN. (LDAP *injection*
  beyond sign-in is `security-review` V1 territory — don't double-report.)
- `ldaps://` or StartTLS with certificate validation on the bind channel — a
  plain simple bind sends the password cleartext.
- Directory service-account credentials not hardcoded or committed.

## Output

Report each finding as a single list item:

- **[severity] ASVS category** — `file:line`
  **Issue:** what is wrong and how an attacker exploits it.
  **Fix:** the concrete change that resolves it.

`severity` reflects who can exploit it pre-auth and what identity they gain:
**critical** — an unauthenticated attacker can bypass login or forge an
identity (signature never verified, `alg` confusion, empty-password LDAP bind,
MFA or recovery bypass, forgeable session cookie); **high** — account takeover
behind a common precondition (missing `state`/PKCE/`nonce`, `redirect_uri`
prefix match, guessable or long-lived reset token, session fixation, identity
keyed on email); **medium** — weakened protections (weak KDF or parameters,
user enumeration, missing cookie attributes, missing rate limits or lockout);
**low** — hardening and hygiene (`__Host-` prefix, timeout tuning, policy
nits). The classifier is the ASVS 5.0 category — usually `V6 Authentication`,
`V7 Session Management`, `V9 Self-contained Tokens`, or `V10 OAuth & OIDC`;
use `V11 Cryptography` for password-storage KDF findings and `V3 Web Frontend
Security` for cookie-attribute findings, matching `security-review`'s
vocabulary. Order findings by severity, highest first, keeping one issue per
finding. For example:

- **[critical] V9 Self-contained Tokens** — `app/auth.py:42`
  **Issue:** `jwt.decode(token, options={"verify_signature": False})` trusts
  whatever claims the client sends, so anyone can mint a token for any user
  and bypass login entirely.
  **Fix:** verify with the pinned issuer key and `algorithms=["RS256"]`, and
  validate `aud`, `iss`, and `exp`.

Verify before reporting: confirm the framework or library doesn't already
enforce the control (many OAuth/session libraries validate `state`, rotate
IDs, or pin algorithms by default) and that no guard sits outside the diff;
quote the offending line in the Issue, and drop anything without a concrete
attacker path to a forged or stolen identity. Prefer the few findings that
matter; if more than ~10 survive, report the ones worth a human's time and
summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (3 files): 2 findings, worst critical.` If the diff
touches no authentication code, say so rather than reviewing other code. If
the authentication changes are sound, say so explicitly rather than
manufacturing findings.
