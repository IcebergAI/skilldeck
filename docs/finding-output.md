# Finding output format

Every review skill (`security-review`, `authentication-review`,
`ci-workflow-review`, `iac-review`, `code-smells`, `dependency-review`,
`test-review`, and the review half of `logging`) reports its findings in one
shared shape. A consistent shape means findings from different skills can be
read, sorted, deduplicated, and posted as inline PR comments without per-skill
parsing.

Skills are installed as standalone files, so they cannot link back to this
document — the canonical format is **inlined verbatim into each skill's `## Output`
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
| `severity` | `critical` \| `high` \| `medium` \| `low` | Impact/priority of the finding. Each skill says how it weights severity. |
| `classifier` | skill-specific taxonomy tag | The label that says *what kind* of finding it is — see below. |
| `location` | `` `file:line` `` | The most precise pointer available. Dependency findings use `package old→new` instead, since the issue is the package, not a line. |
| `Issue` | one sentence | What is wrong. Security findings also state how it could be exploited. |
| `Fix` | one sentence | The specific, actionable change — not "consider improving". |

### Per-skill `classifier` vocabulary

| Skill | `classifier` is… | Example |
| --- | --- | --- |
| `security-review` | the ASVS 5.0 category | `V8 Authorization` |
| `authentication-review` | the ASVS 5.0 category (V6/V7/V9/V10; V11 for password-storage KDFs, V3 for cookie attributes) | `V10 OAuth & OIDC` |
| `ci-workflow-review` | the CICD-SEC category | `CICD-SEC-4 Poisoned Pipeline Execution` |
| `iac-review` | the misconfiguration kind | `Open security group`, `Wildcard IAM` |
| `code-smells` | the smell and its group | `Long Method (Bloaters)` |
| `dependency-review` | the advisory ID or supply-chain concern | `CVE-2024-12345`, `Typosquatting` |
| `test-review` | the weakness kind | `Coverage gap`, `Assertion-free test` |
| `logging` | the logging issue kind | `Secret in log`, `Log injection` |
| `resilience-review` | the resilience concern | `Missing timeout`, `Retry without backoff` |
| `migration-review` | the migration hazard | `Blocking lock`, `Backward-incompatible change` |

## Shared rules

- **Order by severity**, highest first.
- **One issue per finding** — don't bundle unrelated problems into one item.
- **Don't manufacture findings.** If the change is clean, say so explicitly
  rather than padding the report.
- Prioritize: not every finding is worth acting on now: say which matter.

## Example

```
- **[high] V8 Authorization** — `api/orders.py:42`
  **Issue:** the handler trusts a client-supplied `user_id` to scope the query, so any
  caller can read another user's orders (IDOR).
  **Fix:** derive the user from the authenticated session, not the request body.
```
