# Finding output format

Every review skill (`security-review`, `authentication-review`,
`llm-integration-review`, `privacy-review`, `ci-workflow-review`,
`iac-review`, `dependency-review`, `code-smells`, `test-review`,
`resilience-review`, `migration-review`, and the review half of `logging`)
reports its findings in one shared shape, rated on one shared severity
rubric. A consistent shape means findings from different skills can be
read, sorted, deduplicated, and posted as inline PR comments without per-skill
parsing.

Skills are installed as standalone files, so they cannot link back to this
document — the canonical format, and the one-paragraph form of the
[severity rubric](#severity-rubric), are **inlined into each skill's `## Output`
section**. This file is the source of truth; when you add or change a review
skill, make its `## Output` match what is described here.

## The format

Report each finding as a single top-level list item:

```
- **[severity] classifier** — `location`
  **Issue:** what is wrong (and, for security findings, how it could be exploited).
  **Fix:** the concrete change that resolves it.
```

## Fields

| Field | Values / form | Notes |
| --- | --- | --- |
| `severity` | `critical` \| `high` \| `medium` \| `low` | Rated on the [severity rubric](#severity-rubric) below. |
| `classifier` | skill-specific taxonomy tag | The label that says *what kind* of finding it is — see below. |
| `location` | `` `file:line` `` | The most precise pointer available. Dependency findings use `package old→new` instead, since the issue is the package, not a line. |
| `Issue` | one or two sentences | What is wrong. Security findings also state how it could be exploited. |
| `Fix` | one or two sentences | The specific, actionable change — not "consider improving". |

### Per-skill `classifier` vocabulary

| Skill | `classifier` is… | Example |
| --- | --- | --- |
| `security-review` | the ASVS 5.0 category | `V8 Authorization` |
| `authentication-review` | the ASVS 5.0 category (V6/V7/V9/V10; V11 for password-storage KDFs, V3 for cookie attributes) | `V10 OAuth & OIDC` |
| `llm-integration-review` | the OWASP Top 10 for LLM Applications 2026 entry | `LLM10:2026 Improper Output Handling` |
| `privacy-review` | the privacy concern (grounded in ASVS 5.0 V14) | `Data minimisation`, `Third-party sharing` |
| `ci-workflow-review` | the CICD-SEC category | `CICD-SEC-4 Poisoned Pipeline Execution` |
| `iac-review` | the misconfiguration kind | `Open security group`, `Wildcard IAM` |
| `code-smells` | the smell and its group | `Long Method (Bloaters)` |
| `dependency-review` | the advisory ID or supply-chain concern | `CVE-2024-12345`, `Typosquatting` |
| `test-review` | the weakness kind | `Coverage gap`, `Assertion-free test` |
| `logging` | the logging issue kind | `Secret in log`, `Log injection` |
| `resilience-review` | the resilience concern | `Missing timeout`, `Retry without backoff` |
| `migration-review` | the migration hazard | `Blocking lock`, `Backward-incompatible change` |

## Severity rubric

Severity is **impact × likelihood**, combined as in the
[OWASP Risk Rating Methodology](https://owasp.org/www-community/OWASP_Risk_Rating_Methodology)
(risk = likelihood × impact, read off its overall-severity matrix). Rate a
finding where the changed code actually runs, and when that is uncertain
(environment, deploy model, who can trigger it) say which assumption the rating
rests on.

- **Likelihood** — how readily it is triggered or exploited. *High*: anyone who
  can reach it (an unauthenticated user, an outside contributor who can open a
  PR/MR, anyone who can read the repository or the logs), or routine operation.
  *Medium*: a common precondition (an authenticated user, a collaborator, a
  routine dependency failure, production load). *Low*: an unusual precondition
  (an insider, a compromised upstream publisher, rare timing or configuration).
- **Impact** — what happens when it is. *High*: code execution, authentication
  bypass, stolen credentials or bulk data, data loss, or an outage. *Medium*:
  limited exposure, degraded service, duplicated side effects, or a defect
  allowed to ship. *Low*: defense in depth, hygiene, cosmetics.

| Impact ↓ / Likelihood → | Low | Medium | High |
| --- | --- | --- | --- |
| **High** | medium | high | critical |
| **Medium** | low | medium | high |
| **Low** | low | low | medium |

(OWASP's matrix calls the low/low cell "Note"; skills fold it into `low` or
drop it.) This is the one-paragraph form of the matrix, covering every cell,
that every skill inlines word for word:

> Rate `severity` on the shared severity rubric, impact × likelihood:
> **critical** — high impact (code execution, auth bypass, stolen credentials or
> bulk data, data loss, an outage), readily triggered (by anyone who can reach
> it, or in routine operation); **high** — high impact behind a common
> precondition (an authenticated user, a collaborator, a routine failure), or
> medium impact (limited exposure, degraded service) readily triggered;
> **medium** — high impact only under an unusual precondition, medium impact
> behind a common one, or low impact readily triggered (a weakened defense
> anyone can reach); **low** — medium impact only under an unusual
> precondition, or low impact behind any precondition (most defense in depth
> and hygiene).

After it, a skill keeps at most a short list of anchors for its own domain,
consistent with the matrix — never one that contradicts it.

**Critical is reserved** for security-exploitable, data-loss, or outage-causing
findings, so it means the same thing in a combined report:

- `code-smells` and `test-review` **top out at high**. A smell or a test gap
  makes a defect more likely but causes none by itself, so its impact is medium
  at most.
- `resilience-review` and `migration-review` use **critical** only for an
  outage or data loss.

### Canonical ratings for shared defects

Some defects can be found by more than one skill. They carry the same rating
whichever skill reports them, and only the owner (see
[Which skill owns what](#which-skill-owns-what)) reports them.

**A live credential exposed to a wider audience is critical.** A working
password, API key, token, or private or signing key committed to the repository
(deleting it later leaves it in history), baked into an image or template, or
written to logs or CI output that people who shouldn't hold it can read —
[CICD-SEC-6 Insufficient Credential Hygiene](https://owasp.org/www-project-top-10-ci-cd-security-risks/CICD-SEC-06-Insufficient-Credential-Hygiene)
describes both routes. Removing the value doesn't un-expose it, so the Fix must
also revoke and rotate the credential: a potentially compromised secret must be
revoked
([OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html),
§2.7.3). A placeholder or test value is not live. The classifier is the owner's:

| Where the credential is | Owner | Classifier |
| --- | --- | --- |
| Application source or config | `security-review` | `V13 Configuration` |
| Application logs | `logging` | `Secret in log` |
| Pipeline config or CI job output | `ci-workflow-review` | `CICD-SEC-6 Insufficient Credential Hygiene` |
| IaC templates, variables, manifests, image layers | `iac-review` | `Secret in code` |

**A mutable pin is medium.** Third-party code referenced by something its
publisher can repoint — a tag or branch instead of a commit SHA, an image tag
instead of an `@sha256:` digest, a package at `latest` or in a range no
committed lockfile pins. Whatever it resolves to runs with the job's or
workload's access, but abusing it takes a compromised publisher, an unusual
precondition — the "dependency hijacking" vector of
[CICD-SEC-3 Dependency Chain Abuse](https://owasp.org/www-project-top-10-ci-cd-security-risks/CICD-SEC-03-Dependency-Chain-Abuse);
the [OpenSSF Scorecard Pinned-Dependencies check](https://github.com/ossf/scorecard/blob/main/docs/checks.md#pinned-dependencies)
also rates it Medium. A version *known* to be malicious or compromised is not a
pin finding: `dependency-review` reports it under its advisory. Each artifact
type has one owner:

| Pinned artifact | Owner | Classifier |
| --- | --- | --- |
| CI config: actions, reusable workflows, CI `include:`s and components, job and service images | `ci-workflow-review` | `CICD-SEC-3 Dependency Chain Abuse` |
| IaC: Dockerfile `FROM`, compose and Kubernetes/Helm images, Terraform/OpenTofu module sources | `iac-review` | `Mutable pin` |
| Package manifests and lockfiles | `dependency-review` | `Mutable pin` |

## Which skill owns what

`security-review` covers the application at breadth; companion skills go deep on
one area and own it:

| Area | Owner | Instead of |
| --- | --- | --- |
| Authentication depth — ASVS V6, V7, V9, V10 (passwords, MFA, sessions and cookies, tokens, OAuth/OIDC, SAML and LDAP sign-in) | `authentication-review` | `security-review` |
| Security logging — ASVS V16 (events logged, secrets or PII in logs, log injection) | `logging` | `security-review`, `authentication-review` |
| LLM and agent integrations — prompts, model output reaching sinks, tools and agent loops, MCP servers and config, RAG retrieval, model loading | `llm-integration-review` | `security-review` |
| Personal-data handling — ASVS V14 privacy (minimisation, sharing with trackers and processors, consent-gated tracking, retention and deletion, sensitive data at rest, PII in URLs, caches and client storage); PII in logs stays with `logging`, in prompts with `llm-integration-review` | `privacy-review` | `security-review` |
| Pipeline config — workflows, CI includes, job images, runners, CI variables and tokens | `ci-workflow-review` | `security-review`, `dependency-review` |
| Supply chain — package manifests and lockfiles (advisories, provenance, malicious or unmaintained packages) | `dependency-review` | `security-review` (15.2.1, 15.2.4) |
| Infrastructure config — Terraform/CloudFormation/Pulumi, Kubernetes/Helm, Dockerfiles, compose | `iac-review` | `security-review`, `dependency-review` |

When the owning skill runs in the same review, the others leave its area to it.
When one agent runs several skills into one report, each defect appears once,
under the owning skill's classifier. When the owner isn't running, the skill
that finds the defect reports it with its own classifier and the canonical
rating.

## Shared rules

- **Order by severity**, highest first.
- **One issue per finding** — don't bundle unrelated problems into one item.
- **Verify before reporting**, and keep the few findings that matter: if more
  than ~10 survive, report the ones worth a human's time and summarize the rest
  in a line.
- **Don't manufacture findings.** If the change is clean, say so explicitly
  rather than padding the report; if it touches nothing in the skill's area,
  say so and stop.
- **Open with one line** stating what was reviewed and the outcome, using the
  same three-dot range as the diff, e.g.
  `Reviewed origin/main...HEAD (4 files): 2 findings, worst high.`

## Example

```
- **[high] V8 Authorization** — `api/orders.py:42`
  **Issue:** the handler trusts a client-supplied `user_id` to scope the query, so any
  signed-in user can read another user's orders (IDOR).
  **Fix:** derive the user from the authenticated session, not the request body.
```
