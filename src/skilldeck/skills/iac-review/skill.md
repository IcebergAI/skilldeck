# IaC Review

Review the **pending changes on the current branch** to infrastructure-as-code
— Terraform/OpenTofu, CloudFormation, Pulumi, Kubernetes manifests and Helm
charts, Dockerfiles and compose files — for misconfigurations that expose
infrastructure. The checklists follow the hardening baselines of the
[CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks), the Kubernetes
[Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
(baseline/restricted profiles), and the OWASP
[Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html).

Judge by blast radius and environment: a permissive rule in an isolated dev
sandbox is not a production exposure — but config has a habit of being copied
to prod, so say which assumption your severity rests on. Note the platform
where behavior differs (AWS/GCP/Azure defaults are not the same).

## Scope

1. Determine the diff: `git fetch`, then `git diff origin/<base>...HEAD`
   (default base: `main`/`master`; with no remote, the local base), plus
   uncommitted changes (`git diff HEAD`) and untracked files
   (`git ls-files --others --exclude-standard`; read them whole). If you are
   already on the base branch, review the uncommitted changes instead.
2. Focus on infrastructure files: `*.tf`/`*.tfvars`, CloudFormation/CDK
   templates, `k8s/`/`manifests/`/`charts/` YAML, `Dockerfile*`,
   `docker-compose*`, Ansible playbooks, and the variables/values files that
   feed them.
3. Read the whole resource around each hunk, not just the diff — a rule's
   exposure depends on sibling attributes (the VPC it's in, the principal it
   binds, the profile it inherits) that may sit outside the changed lines.
4. If the project already runs an IaC scanner (Checkov, tfsec/Trivy,
   kube-score, conftest/OPA, kics), don't re-flag what it enforces; focus on
   what it can't see (intent, environment, blast radius).
5. This skill owns infrastructure config, including its secrets and its image
   and module pins; pipeline files belong to `ci-workflow-review` and package
   manifests to `dependency-review`. If the owner runs in the same review,
   leave its area to it; in a combined report, give each defect once, under
   the owner's classifier.

## What to look for (by category)

### Network exposure

- Security groups / firewall rules open to the world (`0.0.0.0/0`, `::/0`) —
  worst on management and data ports (SSH 22, RDP 3389, database ports).
- Storage buckets or object containers made public (ACLs, policies, or
  disabled public-access blocks); public IPs or public subnets for internal
  services; load balancers or endpoints without TLS.
- Kubernetes: `hostNetwork`/`hostPort`, NodePort services where an ingress
  belongs, overly broad NetworkPolicy (or none where the project uses them).

### Identity & access (least privilege)

- Wildcard IAM — `Action: "*"`, `Resource: "*"`, `Principal: "*"` — or
  admin-equivalent managed policies attached to service roles.
- Kubernetes RBAC with wildcard verbs/resources, `cluster-admin` bindings for
  workloads, service-account tokens automounted where unused.
- Cross-account/public sharing of images, snapshots, or key material.

### Secrets & state

- Credentials hardcoded in templates, variables, `user_data`/cloud-init, or
  Dockerfile `ENV`/`ARG` (build args persist in image history); Kubernetes
  `Secret` data committed in a plain manifest.
- Terraform state for shared infrastructure kept local or in an unencrypted,
  unversioned backend — state contains every secret the resources do.
- Secrets passed as environment variables where the platform offers a secrets
  manager or mounted secret.

### Data protection

- Encryption at rest disabled (or default keys where customer-managed keys
  are the project norm); encryption in transit not enforced.
- Backups, versioning, deletion protection, or access logging disabled on
  stateful or sensitive stores; public database snapshots.

### Containers & pods (PSS baseline/restricted)

- `privileged: true`; host namespaces (`hostNetwork`, `hostPID`, `hostIPC`)
  or `hostPath` mounts; the Docker socket mounted into a container; added
  Linux capabilities beyond the PSS safe list.
- Missing `runAsNonRoot`/`USER` (container runs as root),
  `allowPrivilegeEscalation` not `false`, root filesystem not read-only where
  it could be, seccomp/AppArmor defaults disabled.
- No CPU/memory limits (noisy-neighbor and DoS surface); bloated base images
  where minimal ones fit.

### Mutable pins

- Third-party images by tag (none means `:latest`) rather than `@sha256:`
  digest — tags can be moved, digests are fixed
  ([Kubernetes images](https://kubernetes.io/docs/concepts/containers/images/));
  third-party registry modules without an exact `version` (none, or a range —
  the lock file records providers, not modules)
  ([module version](https://developer.hashicorp.com/terraform/language/modules/syntax#version),
  [lock file](https://developer.hashicorp.com/terraform/language/files/dependency-lock)),
  or git module sources whose `ref` is not a commit SHA
  ([selecting a revision](https://developer.hashicorp.com/terraform/language/modules/sources#selecting-a-revision)).

### Change safety

- A rename or type change that forces **replacement of a stateful resource**
  (database, volume, queue) hidden in an innocuous-looking diff.
- Deletion protection or `prevent_destroy` removed; lifecycle rules that
  purge data earlier than intended.

## Output

Report each finding as a single list item:

- **[severity] misconfiguration kind** — `file:line`
  **Issue:** what is exposed or weakened, to whom, and under which environment
  assumption.
  **Fix:** the concrete configuration change (restrict the CIDR, drop the
  capability, scope the policy, move the secret).

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
Here: **critical** — internet-facing attack surface (a bucket or security group
open to the world on a sensitive port), or a live credential committed in
templates, variables, manifests, or image layers (the Fix must also
[revoke and rotate](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
it); **high** — a privilege-escalation path or unencrypted/unprotected
sensitive data; **medium** — a mutable pin (classified `Mutable pin`), or a
hardening regression contained inside the cluster or network boundary. The
classifier is the misconfiguration kind (e.g. `Open security group`,
`Wildcard IAM`, `Privileged container`, `Secret in code`). Order findings by
severity, highest first, keeping one issue per finding. For example:

- **[critical] Open security group** — `infra/network.tf:23`
  **Issue:** the new ingress rule allows `0.0.0.0/0` on port 22, exposing SSH
  on every instance in the group to the internet; brute-force and scanner
  traffic reach it immediately.
  **Fix:** restrict the CIDR to the bastion/VPN range, or drop the rule and
  use the cloud's session-manager access instead.

Verify before reporting: confirm the exposure is real in context — the
resource's siblings (VPC, public-access block, inherited profile) may already
contain it — quote the offending attribute in the Issue, and drop anything you
cannot tie to a concrete exposure. Prefer the few findings that matter; if
more than ~10 survive, report the ones worth a human's time and summarize the
rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed origin/main...HEAD (3 files): 1 finding, critical.` If the diff
touches no infrastructure code, say so and stop. If the infrastructure changes
are sound, say so explicitly rather than manufacturing findings.
