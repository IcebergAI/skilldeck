# IaC Review

Review the **pending changes on the current branch** to infrastructure-as-code
— Terraform/OpenTofu, CloudFormation, Pulumi, Kubernetes manifests and Helm
charts, Dockerfiles and compose files — for misconfigurations that expose
infrastructure. The checklists follow the hardening baselines of the
[CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks), the Kubernetes
[Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
(baseline/restricted profiles), and the OWASP
[Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html).
Pair with `ci-workflow-review` for the pipelines that apply this code and
`security-review` for the application itself.

Judge by blast radius and environment: a permissive rule in an isolated dev
sandbox is not a production exposure — but config has a habit of being copied
to prod, so say which assumption your severity rests on. Note the platform
where behavior differs (AWS/GCP/Azure defaults are not the same).

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
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
- No CPU/memory limits (noisy-neighbor and DoS surface); mutable `:latest`
  image tags; bloated base images where minimal ones fit.

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

`severity` reflects exposure and blast radius: **critical** — internet-facing
attack surface or leaked credential (a bucket or security group open to the
world on a sensitive port, a secret in code); **high** — a privilege-escalation
path or unencrypted/unprotected sensitive data; **medium** — a hardening
regression contained inside the cluster or network boundary; **low** —
hygiene. The classifier is the misconfiguration kind (e.g. `Open security
group`, `Wildcard IAM`, `Privileged container`, `Secret in code`). Order
findings by severity, highest first, keeping one issue per finding.
For example:

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
`Reviewed main..HEAD (3 files): 1 finding, critical.` If the diff touches no
infrastructure code, say so rather than reviewing application code. If the
infrastructure changes are sound, say so explicitly rather than manufacturing
findings.
