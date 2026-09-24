"""Structure checks for the golden-diff eval fixtures.

The eval runner itself (``evals/run_evals.py``) calls a paid agent and is run
manually; these tests keep the fixtures healthy in CI without any API calls:
every fixture must load, target a bundled skill, plant its defects inside the
reviewed diff with keywords that describe the defect rather than echo the code,
and produce a working git repo. Sample reports check each planted fixture's
keywords from both sides: a correct report passes, and a finding about a
different real defect in the same file satisfies no plant. The scorer is
covered by test_eval_scoring.py.
"""

import dataclasses
import subprocess

import pytest
import run_evals  # loaded from evals/run_evals.py by conftest.py

FIXTURE_DIRS = sorted(p for p in run_evals.FIXTURES.iterdir() if p.is_dir())


def _finding(severity, kind, location, issue, fix):
    return (
        f"- **[{severity}] {kind}** — `{location}`\n"
        f"  **Issue:** {issue}\n"
        f"  **Fix:** {fix}\n"
    )


# fixture -> (a correct report: one realistic finding per plant; findings
# about other real defects in the planted file, none of which may satisfy a
# plant). Keeps keywords from being too narrow (a stem, a missing inflection)
# or so generic that a neighbouring finding passes for the plant.
SAMPLE_REPORTS = {
    "authentication-review": (
        [
            _finding(
                "high",
                "V10 OAuth & OIDC",
                "app/sso.py:19",
                "the authorization request carries no `state` or PKCE "
                "`code_challenge` and the callback accepts any code, so an "
                "attacker can sign a victim into the attacker's account "
                "(login CSRF).",
                "bind a per-request state and PKCE verifier to the session and "
                "check both in the callback.",
            ),
            _finding(
                "high",
                "V10 OAuth & OIDC",
                "app/sso.py:46",
                "the local account is keyed on the userinfo `email` claim, which "
                "is reassignable and may be unverified, so whoever the IdP later "
                "gives that address takes over the account.",
                "key the account on the issuer plus the stable `sub` claim.",
            ),
        ],
        [
            _finding(
                "medium",
                "V10 OAuth & OIDC",
                "app/sso.py:30",
                "the token response is used without checking its HTTP status or "
                "`error` field, so an IdP error surfaces as a KeyError and a 500.",
                "call `raise_for_status()` and handle an error response.",
            ),
            _finding(
                "medium",
                "V10 OAuth & OIDC",
                "app/sso.py:23",
                "the flow requests the `openid` scope but never validates an ID "
                "token (signature, `iss`, `aud`, `nonce`), trusting userinfo "
                "instead.",
                "validate the ID token against the IdP's JWKS.",
            ),
        ],
    ),
    "authentication-review-saml": (
        [
            _finding(
                "critical",
                "V6 Authentication",
                "app/saml_acs.py:22",
                "the return value of `verify()` is thrown away and `NameID` is "
                "read from the raw document, so an attacker can wrap a validly "
                "signed response around an injected assertion (XML Signature "
                "Wrapping).",
                "read the identity only from the `signed_xml` that `verify()` returns.",
            )
        ],
        [
            _finding(
                "high",
                "V6 Authentication",
                "app/saml_acs.py:24",
                "the assertion's `NotOnOrAfter`, `AudienceRestriction` and "
                "`InResponseTo` are unverified, so a captured assertion can be "
                "replayed.",
                "validate the conditions and reject reused assertion IDs.",
            )
        ],
    ),
    "ci-workflow-review": (
        [
            _finding(
                "critical",
                "CICD-SEC-4 Poisoned Pipeline Execution",
                ".github/workflows/coverage-report.yml:26",
                "the `workflow_run` job writes files from the PR run's artifact "
                "to `$GITHUB_ENV` unchecked; a fork controls that run, and a "
                "newline in `pr-number` sets arbitrary environment variables "
                "(`BASH_ENV` pointing at a script in the artifact) for the next "
                "step, which then runs the fork's code with a write token.",
                "validate the PR number as an integer and pass values through "
                "step outputs, never the environment file.",
            ),
            _finding(
                "medium",
                "CICD-SEC-3 Dependency Chain Abuse",
                ".github/workflows/coverage-report.yml:34",
                "`marocchino/sticky-pull-request-comment@v2` is a mutable tag, "
                "so whoever controls the action can change the code that runs "
                "with this job's pull-requests write token.",
                "pin the action to a full-length commit SHA.",
            ),
        ],
        [
            _finding(
                "medium",
                "CICD-SEC-4 Poisoned Pipeline Execution",
                ".github/workflows/coverage-report.yml:33",
                "the PR number comes from the fork's artifact, so a fork can "
                "make the bot label and comment on someone else's pull request.",
                "check the number against `github.event.workflow_run.head_sha`.",
            )
        ],
    ),
    "ci-workflow-review-gitlab": (
        [
            _finding(
                "critical",
                "CICD-SEC-4 Poisoned Pipeline Execution",
                ".gitlab-ci.yml:34",
                "announce-release hands the commit title to `sh -c`, which "
                "re-parses it as shell, so a crafted MR title or source branch "
                "runs with the default branch's protected variables.",
                'pass the title as `"$1"` to a quoted script.',
            ),
            _finding(
                "critical",
                "CICD-SEC-7 Insecure System Configuration",
                ".gitlab-ci.yml:21",
                "build-image sends merge request pipelines to a privileged "
                "docker-in-docker runner, so any MR author gets root on the "
                "runner host.",
                "build with an unprivileged builder on an isolated runner.",
            ),
        ],
        [
            _finding(
                "medium",
                "CICD-SEC-3 Dependency Chain Abuse",
                ".gitlab-ci.yml:14",
                "the `docker:24` and `alpine:3.20` images are pulled by mutable "
                "tag, so a republished tag changes what the jobs run.",
                "pin each image by digest.",
            )
        ],
    ),
    "code-smells": (
        [
            _finding(
                "medium",
                "Duplicate Code (Dispensables)",
                "billing/quotes.py:8",
                "`quote_total` repeats `invoice_total`'s subtotal, loyalty "
                "discount, tax and rounding step for step, so the next pricing "
                "rule has to be made in both places.",
                "call `invoice_total(quote, customer)` instead.",
            )
        ],
        [
            _finding(
                "low",
                "Primitive Obsession (Bloaters)",
                "billing/quotes.py:9",
                "amounts are bare floats rounded ad hoc, so currency and "
                "rounding rules are left to every caller.",
                "introduce a Money value (a Decimal plus its currency).",
            )
        ],
    ),
    "dependency-review": (
        [
            _finding(
                "high",
                "Dependency confusion",
                "corp-auth-client ~=2.4 (corp index → --extra-index-url)",
                "pip gives `--index-url` and `--extra-index-url` no priority, so "
                "anyone who publishes corp-auth-client with a higher version on "
                "PyPI gets their code installed. Direct dependency.",
                "resolve corp-* packages only from the corp index.",
            )
        ],
        [
            _finding(
                "medium",
                "Provenance",
                "requirements.txt:3",
                "click and requests now come straight from the public index "
                "instead of the corp mirror, skipping its caching and scanning.",
                "keep the mirror as the only index.",
            )
        ],
    ),
    "iac-review": (
        [
            _finding(
                "high",
                "Wildcard IAM",
                "infra/iam.tf:24",
                "the app role gets `s3:*` on `*` although it only writes to the "
                "exports bucket, so a compromised app can read, overwrite or "
                "delete every bucket in the account and change bucket policies.",
                "grant `s3:PutObject` on the exports bucket's ARN only.",
            )
        ],
        [
            _finding(
                "low",
                "Hygiene",
                "infra/iam.tf:29",
                "the policy is an inline `aws_iam_role_policy`, which can't be "
                "attached to another role or reviewed with the managed policies.",
                "define it as an `aws_iam_policy` with an attachment.",
            )
        ],
    ),
    "logging": (
        [
            _finding(
                "high",
                "Log injection",
                "auth/session.py:15",
                "the submitted username is written into the failed-login "
                "warning unescaped, so a CR/LF in it forges extra log lines, "
                "such as a fake successful login.",
                "escape control characters, or log the username as a structured field.",
            )
        ],
        [
            _finding(
                "medium",
                "Logging DoS",
                "auth/session.py:15",
                "every failed login writes a warning, so a scripted "
                "credential-stuffing run fills the log store.",
                "rate-limit or aggregate the failed-login events.",
            )
        ],
    ),
    "migration-review": (
        [
            _finding(
                "critical",
                "Backward-incompatible change",
                "db/migrate/20260704120000_rename_kind_to_event_type_on_events.rb:3",
                "the rename lands while the old release still serves traffic "
                "and writes `kind` on every request, so its inserts into "
                "`events` fail until the rollout finishes.",
                "expand/contract: add `event_type`, write both, backfill, "
                "switch reads, then drop `kind` in a later release.",
            )
        ],
        [
            _finding(
                "medium",
                "Blocking lock",
                "db/migrate/20260704120000_rename_kind_to_event_type_on_events.rb:3",
                "`RENAME COLUMN` needs an ACCESS EXCLUSIVE lock, and with no "
                "`lock_timeout` it waits behind any long query on `events`, "
                "blocking every insert queued behind it.",
                "set a short `lock_timeout` and retry the migration.",
            )
        ],
    ),
    "resilience-review": (
        [
            _finding(
                "high",
                "Retry without backoff",
                "services/client.py:14",
                "the loop retries at once, five times, so when the shipping "
                "service struggles every caller multiplies its load (a retry "
                "storm).",
                "back off exponentially with jitter between attempts.",
            ),
            _finding(
                "medium",
                "Non-idempotent retry",
                "services/client.py:16",
                "a read timeout after the shipment was created sends the POST "
                "again, so the order ships twice.",
                "send an idempotency key the shipping service dedupes on.",
            ),
        ],
        [
            _finding(
                "medium",
                "Deadline not propagated",
                "services/client.py:19",
                "five attempts of up to 13s each can hold the caller for over a "
                "minute, longer than the request that triggered it will wait.",
                "pass the caller's remaining deadline down and stop when it runs out.",
            )
        ],
    ),
    "security-review": (
        [
            _finding(
                "high",
                "V5 File Handling",
                "app/orders.py:26",
                "the `name` query parameter is joined onto the documents path "
                "unchecked, so `../` segments or an absolute path let a "
                "signed-in user read any file the app can (path traversal).",
                "serve the file with `send_from_directory`, or look the "
                "document up by ID.",
            )
        ],
        [
            _finding(
                "low",
                "V16 Security Logging and Error Handling",
                "app/orders.py:22",
                "an anonymous request raises KeyError on `session['user_id']` "
                "and returns a 500.",
                "check for a signed-in user and return 401.",
            )
        ],
    ),
    "test-review": (
        [
            _finding(
                "high",
                "Assertion-free test",
                "tests/test_discount.py:8",
                "`test_coupon` calls `apply_discount` but never checks the "
                "result, so a broken coupon still passes.",
                "assert the discounted price.",
            )
        ],
        [
            _finding(
                "high",
                "Coverage gap",
                "tests/test_discount.py:8",
                "nothing tests an out-of-range percent or an unknown coupon.",
                "add tests that assert `ValueError` for `percent=150` and "
                '`coupon="BOGUS"`.',
            )
        ],
    ),
}


def _bundled_skill_names():
    from skilldeck.adapters import ADAPTERS
    from skilldeck.registry import discover_skills

    return {s.name for s in discover_skills(known_agents=set(ADAPTERS))}


def test_every_fixture_dir_is_named_for_its_skill():
    # A skill may have several fixtures: the directory is either the skill name
    # or the skill name plus a "-<variant>" suffix (e.g. a GitLab variant).
    assert FIXTURE_DIRS, "no eval fixtures found"
    for path in FIXTURE_DIRS:
        fixture = run_evals.load_fixture(path)
        assert path.name == fixture.skill or path.name.startswith(fixture.skill + "-")


def test_there_is_a_clean_diff_fixture():
    # false-positive pressure needs at least one change that should pass clean
    assert any(not run_evals.load_fixture(p).plants for p in FIXTURE_DIRS)


@pytest.mark.parametrize("path", FIXTURE_DIRS, ids=lambda p: p.name)
def test_fixture_is_well_formed(path):
    fixture = run_evals.load_fixture(path)
    assert fixture.skill in _bundled_skill_names()
    assert (path / "base").is_dir()
    assert (path / "change").is_dir()
    for plant in fixture.plants:
        assert (path / "change" / plant.file).is_file(), (
            f"plant file {plant.file} not in change/"
        )
    if not fixture.plants:
        # a clean-diff fixture's max-findings is its false-positive tolerance
        assert fixture.max_findings <= 2, "keep a clean fixture's tolerance small"


@pytest.mark.parametrize("path", FIXTURE_DIRS, ids=lambda p: p.name)
def test_plant_keywords_describe_the_defect_not_the_code(path):
    # A keyword copied from the planted code (a variable, an event name, a
    # CIDR) is satisfied by any report that quotes the line, whether or not it
    # identified the defect. Same whole-word matching as the scorer.
    fixture = run_evals.load_fixture(path)
    for plant in fixture.plants:
        code = (path / "change" / plant.file).read_text(encoding="utf-8")
        echoed = [k for k in plant.keywords if run_evals.mentions(code, k)]
        assert not echoed, (
            f"{plant.file}: keyword(s) {echoed} appear verbatim in the planted "
            "code; keywords must describe the defect, not echo the code"
        )


def test_every_planted_fixture_has_sample_reports():
    planted = {p.name for p in FIXTURE_DIRS if run_evals.load_fixture(p).plants}
    assert planted == set(SAMPLE_REPORTS), "add a SAMPLE_REPORTS entry"


@pytest.mark.parametrize("name", sorted(SAMPLE_REPORTS))
def test_a_correct_report_passes(name):
    fixture = run_evals.load_fixture(run_evals.FIXTURES / name)
    correct, _ = SAMPLE_REPORTS[name]
    header = f"Reviewed main..HEAD (1 file): {len(correct)} finding(s).\n\n"
    assert run_evals.score(fixture, header + "".join(correct)) == ([], True)


@pytest.mark.parametrize("name", sorted(SAMPLE_REPORTS))
def test_a_neighbouring_finding_satisfies_no_plant(name):
    fixture = run_evals.load_fixture(run_evals.FIXTURES / name)
    # keywords alone must rule the neighbour out, whatever its severity
    plants = [dataclasses.replace(p, min_severity=None) for p in fixture.plants]
    _, neighbours = SAMPLE_REPORTS[name]
    for neighbour in neighbours:
        findings = run_evals.parse_findings(neighbour)
        assert len(findings) == 1
        satisfied = [p.keywords for p in plants if run_evals.satisfies(p, findings[0])]
        assert not satisfied, f"{neighbour!r} satisfies the plant(s) {satisfied}"


@pytest.mark.parametrize("path", FIXTURE_DIRS, ids=lambda p: p.name)
def test_fixture_builds_a_repo_with_the_plant_in_the_diff(path, tmp_path):
    fixture = run_evals.load_fixture(path)
    repo = run_evals.prepare_repo(fixture, tmp_path)
    diff = subprocess.run(
        ["git", "diff", "--name-only", "main...change"],
        cwd=repo,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    changed = set(diff.split())
    assert changed, "change branch has an empty diff"
    for plant in fixture.plants:
        assert plant.file in changed, f"plant {plant.file} is not part of the diff"
    # the skill is installed for claude at project scope by default, in the
    # base commit: neither part of the diff nor an untracked change
    skill_file = f".claude/skills/{fixture.skill}/SKILL.md"
    assert (repo / skill_file).is_file()
    assert skill_file not in changed
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert status == "", f"the review repo has uncommitted changes:\n{status}"
