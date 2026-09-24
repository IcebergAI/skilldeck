# Frontend Security Review

Review the **pending changes on the current branch** that run in the browser —
React, Vue, Angular, Svelte, or plain JavaScript and HTML templates — and the
Content Security Policy (CSP) and other headers that govern the page, for
client-side security defects. The checklist follows
[OWASP ASVS 5.0](https://owasp.org/www-project-application-security-verification-standard/)
V3 Web Frontend Security, the OWASP
[XSS](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html),
[DOM-based XSS](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html),
[CSP](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html),
[HTML5 Security](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html),
[Clickjacking](https://cheatsheetseries.owasp.org/cheatsheets/Clickjacking_Defense_Cheat_Sheet.html),
and [Third-Party JavaScript](https://cheatsheetseries.owasp.org/cheatsheets/Third_Party_Javascript_Management_Cheat_Sheet.html)
cheat sheets, and the security guidance of
[React](https://react.dev/reference/react-dom/components/common#dangerously-setting-the-inner-html),
[Vue](https://vuejs.org/guide/best-practices/security.html),
[Angular](https://angular.dev/best-practices/security),
[Svelte](https://svelte.dev/docs/svelte/@html), and MDN
([CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP),
[`postMessage`](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)).
This skill owns the browser side; `security-review` owns the server side,
including CORS and CSRF checks, and `authentication-review` owns cookies.

Framework auto-escaping is the defense: judge each change by where it steps
outside it, and by what reaches that point.

## Scope

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
2. Look for components and templates, DOM code, `message` listeners, browser
   storage calls, `<script>` tags, `.env*` files and bundler config, and CSP or
   header config (framework config, `<meta>` tags, server or CDN header files).
3. Trace each value that reaches a sink back to its source — the URL (query,
   fragment), another user's stored content, a message, an API response — and
   read the whole component: a sanitizer or check may sit outside the hunk.
4. If the diff touches no browser-side code or headers, say so and stop
   (`no frontend changes`).

## What to look for

Numbers in parentheses are ASVS 5.0 requirement IDs; classify findings by
chapter.

### Escape hatches and DOM XSS sinks (V3 3.2.2; V1 1.2.2, 1.3.1, 1.3.2)

- Untrusted strings rendered as markup: React `dangerouslySetInnerHTML`, Vue
  `v-html`, Svelte `{@html}`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write`. Text belongs in `textContent` or framework interpolation
  (3.2.2); HTML meant to render needs a maintained sanitizer such as DOMPurify,
  applied last (1.3.1).
- Angular `bypassSecurityTrust*` on a value an attacker can influence; untrusted
  input used as a template (a Vue `template` string, string-built templates).
- Strings run as code: `eval`, `new Function`, `setTimeout`/`setInterval` with a
  string (1.3.2).
- Untrusted URLs in `href`, `src`, or a `location` assignment without a scheme
  allow-list: `javascript:` and `data:` URLs run script, and framework escaping
  doesn't check the scheme (1.2.2).

### CSP and framing headers (V3 3.4)

- A CSP added or weakened (3.4.3): `'unsafe-inline'` or `'unsafe-eval'` in
  `script-src`; script sources that admit any host (`*`, `https:`, `data:`); no
  `object-src 'none'` or `base-uri 'none'`; a fixed or reused nonce instead of
  one per response; or only `Content-Security-Policy-Report-Only`, which
  enforces nothing. Prefer a nonce- or hash-based strict policy.
- No `frame-ancestors`, or one allowing any site, on pages with state-changing
  clicks (3.4.6); `X-Frame-Options` alone is obsolete, and `frame-ancestors` in
  a `<meta>` CSP is ignored.
- `nosniff` (3.4.4), HSTS (3.4.1), or `Referrer-Policy` (3.4.5) removed.

### Cross-window messaging (V3 3.5.5)

- A `message` listener that acts without checking `event.origin` against exact
  expected origins (not a substring test such as `indexOf`) and validating the
  message's shape — any window can post to it; message data sent to an HTML
  sink, `eval`, or navigation.
- `postMessage(data, "*")` carrying anything sensitive: name the target origin.

### Browser storage and client bundles (V14 14.3.1, 14.3.3; V13 13.3.1)

- Session identifiers, refresh tokens, or sensitive data in `localStorage`,
  `sessionStorage`, or IndexedDB — one XSS reads all of it; prefer an `HttpOnly`
  cookie. Authenticated data left there after logout (14.3.1).
- Secrets in client code: `NEXT_PUBLIC_*` and `VITE_*` variables are inlined
  into the bundle anyone downloads
  ([Next.js](https://nextjs.org/docs/app/guides/environment-variables),
  [Vite](https://vite.dev/guide/env-and-mode)). Publishable keys meant for
  browsers are not findings.

### Third-party code and navigation (V3 3.6.1, 3.7.2)

- CDN scripts or styles without `integrity` (SRI) and `crossorigin`, or from a
  mutable URL (3.6.1).
- Client-side redirects to a URL from the query or fragment (`?next=`,
  `returnTo`) not limited to same-app paths or an allow-list (3.7.2).

## Output

Report each finding as a single list item:

- **[severity] ASVS category** — `file:line`
  **Issue:** the defect and how an attacker exploits it.
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
Here, script injection (XSS) in a signed-in user's session is high impact — it
acts as the victim: **critical** when anyone can plant it without an account
where others view it, **high** when planting it takes an account or the victim
must open an attacker's link or page (reflected, DOM, or message-borne XSS). A
live secret in client code is always **critical**, and its Fix must also revoke
and rotate it. A weakened CSP, missing `frame-ancestors` on state-changing
pages, a session token moved into web storage, or an open redirect is
**medium**; missing SRI, `nosniff`, or `Referrer-Policy` is **low**. The
classifier is the ASVS 5.0 chapter, e.g. `V3 Web Frontend Security`;
`V1 Encoding and Sanitization` for sanitizers, URL schemes, and `eval`;
`V14 Data Protection` for storage; `V13 Configuration` for secrets. Order
findings by severity, highest first, and keep one issue per finding. For
example:

- **[high] V3 Web Frontend Security** — `src/search/results.ts:27`
  **Issue:** `heading.innerHTML = "Results for " + params.get("q")` writes the
  query string as markup, so a link to `/search?q=<img src=x onerror=...>` runs
  script in the signed-in victim's session (DOM XSS).
  **Fix:** set `heading.textContent` instead; the query is text.

Verify before reporting: trace each candidate from an attacker-controlled
source to the sink, quote the offending line in the Issue, and drop anything
without a concrete path. Prefer the few findings that matter — if more than ~10
survive, report the ones worth a human's time and summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed origin/main...HEAD (3 files): 2 findings, worst high.` If the change
is sound, say so explicitly rather than manufacturing findings.
