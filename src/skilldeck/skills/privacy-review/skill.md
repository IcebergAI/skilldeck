# Privacy Review

Review the **pending changes on the current branch** for defects in how they
handle personal data, grounded in
[OWASP ASVS 5.0 V14 Data Protection](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x23-V14-Data-Protection.md)
(with 3.4.5 and 15.3.1), the
[OWASP Top 10 Privacy Risks](https://owasp.org/www-project-top-10-privacy-risks/)
(P4, P6, P9, P10), the
[OWASP User Privacy Protection Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/User_Privacy_Protection_Cheat_Sheet.html),
the CNIL [GDPR Developer Guide](https://github.com/LINCnil/GDPR-Developer-Guide)
(sheets 7, 9, 13, 14, 16), and the W3C
[fingerprinting guidance](https://www.w3.org/TR/fingerprinting-guidance/).
Leave who may call an endpoint to `security-review`, personal data in logs to
`logging`, and personal data in prompts to `llm-integration-review`.

Stay technical: name the data, where it goes, and the code change. Don't judge
lawfulness or give legal advice — when a finding turns on a legal question (a
legal basis, a new processor or hosting region), say so and leave it to the
team's privacy owner.

## Scope

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
2. Look for personal data in models and migrations, serializers and API
   responses, analytics, error-tracker and ad SDK calls, caches, cookies and
   browser storage, URLs built from user fields, exports, and deletion jobs.
3. Follow each personal field to everywhere it is stored, returned, or sent —
   a serializer, consent check, or purge job may sit outside the diff.
4. If the diff touches no personal data, say so and stop
   (`no personal-data changes`).

## What to look for

### Data minimisation (ASVS 14.2.6, 15.3.1, 14.2.8; P10)

- A response that serializes a whole object or `SELECT *` row where the caller
  needs a few fields; return an explicit field allow-list.
- Fields collected or stored that no feature uses, or kept more precise than
  needed (a full date of birth for an age check, exact location for a city —
  CNIL sheet 7).
- Uploaded files keeping metadata (EXIF GPS, author) the user didn't choose to
  share.

### Third-party sharing (ASVS 14.2.3; P4)

- Personal data (email, name, precise location) sent to analytics, ad
  pixels, session replay, or marketing tools without checking the user's
  consent for that purpose, or sent where a pseudonymous ID would do.
- Error trackers collecting PII: Sentry's `send_default_pii=True`, or a
  `data_collection` dict, whose defaults include user identity and request
  bodies ([Sentry options](https://docs.sentry.io/platforms/python/configuration/options/)).
- A new SDK, processor, or hosting region receiving personal data: state what
  goes where so the team can confirm it is approved (CNIL sheet 9).

### Tracking without consent

- Device or browser fingerprinting (canvas, font or sensor probing, hashed
  headers and IP) — the user can't clear it (W3C) — or cross-site or
  third-party analytics cookies and long-lived identifiers set before consent
  (CNIL sheet 16 exempts only narrow first-party audience measurement; leave
  that call to the privacy owner).

### Retention and deletion (ASVS 14.2.7; P6)

- A new table, bucket, queue, or cache of personal data with no TTL, purge job,
  or deletion path.
- Soft delete that only flags a row and leaves the PII in the active store
  (CNIL sheet 14); backups, exports, or other copies a deletion never reaches.

### Data subject rights (P9)

- New personal-data tables or fields missing from the existing account export
  or account-deletion code; deletion that doesn't reach processors holding
  copies (CNIL sheet 13).

### Unprotected sensitive data (ASVS 14.1.2, 14.2.4)

- Health, precise geolocation, government IDs, biometrics, or financial data in
  a plaintext column or file: private data must be encrypted in storage (User
  Privacy Protection Cheat Sheet). Password hashing is
  `authentication-review`'s.

### PII in URL (ASVS 14.2.1, 3.4.5)

- Emails, names, or identifiers in paths or query strings (GET forms,
  redirects, emailed links): they reach access logs, browser history, and
  scripts that record the page URL, and `Referer` under a policy weaker than
  the `strict-origin-when-cross-origin` default ([MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy)).
  Send them in the body and set an explicit `Referrer-Policy`.

### PII in cache or client storage (ASVS 14.2.2, 14.2.5, 14.3.1–14.3.3)

- Personalised responses a CDN or shared cache can store (no
  `Cache-Control: no-store` or `private`), or server-side caches keyed without
  the user.
- Personal data in `localStorage`, `sessionStorage`, IndexedDB, or cookies
  (session tokens aside), or left there after logout.

## Output

Report each finding as a single list item:

- **[severity] privacy concern** — `file:line`
  **Issue:** what personal data is exposed, to whom, and how.
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
Here, sensitive data (health, precise location, government IDs, biometrics)
or bulk personal data readable by anyone who can reach it (an unauthenticated
response, a public link or bucket) is **critical**; the same behind a sign-in
(any user reads others' sensitive fields), or personal data sent to a third
party without consent in routine operation, is **high**; contact details
over-returned to signed-in users, a personal-data store with no deletion
path, a rights gap, sensitive data in a plaintext column, or PII in a URL is
**medium**; hygiene behind an unusual precondition (a missing `no-store` on a
signed-in page, author metadata on a private upload) is **low**. The classifier is the concern
from the headings above, e.g. `Third-party sharing`. Order findings by
severity, highest first, and keep one issue per finding. For example:

- **[medium] PII in URL** — `app/signup.py:27`
  **Issue:** `redirect(url_for("verify", email=form.email, dob=form.dob))`
  puts the applicant's email and date of birth in the query string, so they
  land in web-server and proxy access logs and in browser history.
  **Fix:** keep both in the server-side session and redirect to `/verify`
  with no personal data in the URL.

Verify before reporting: trace each field to where it is exposed, quote the
offending line in the Issue, and drop anything that isn't personal data or
never leaves its intended audience. Prefer the few findings
that matter — if more than ~10 survive, report the ones worth a human's time
and summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed origin/main...HEAD (4 files): 2 findings, worst high.` If the change
handles personal data soundly, say so explicitly rather than manufacturing
findings.
