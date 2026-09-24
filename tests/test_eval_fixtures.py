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
                ".github/workflows/greet.yml:16",
                "the attacker-controlled PR title is expanded into the `run:` "
                "script of a `pull_request_target` job, so a fork author runs "
                "shell with the base repository's token (script injection).",
                "pass the title through `env:` and quote it.",
            ),
            _finding(
                "critical",
                "CICD-SEC-4 Poisoned Pipeline Execution",
                ".github/workflows/greet.yml:13",
                "`pull_request_target` checks out the PR head and runs its "
                "`scripts/welcome.sh`, so a fork PR runs its own code with the "
                "base repository's token and secrets.",
                "use `pull_request`, or never execute code from the PR head here.",
            ),
        ],
        [
            _finding(
                "high",
                "CICD-SEC-5 Insufficient PBAC",
                ".github/workflows/greet.yml:8",
                "the job sets no `permissions:`, so its token gets the "
                "repository default, which may be write-all.",
                "grant only `pull-requests: write`.",
            )
        ],
    ),
    "ci-workflow-review-env-injection": (
        [
            _finding(
                "critical",
                "CICD-SEC-4 Poisoned Pipeline Execution",
                ".github/workflows/preview.yml:27",
                "the `workflow_run` job writes the fork-controlled artifact's "
                "branch file into `$GITHUB_ENV`, so a newline in it adds "
                "`LD_PRELOAD` for the deploy step that holds the deploy token.",
                "validate the PR number as digits and write only that.",
            ),
            _finding(
                "low",
                "CICD-SEC-6 Insufficient Credential Hygiene",
                ".github/workflows/preview.yml:17",
                "the checkout leaves the job token in `.git/config` for every "
                "later step, though nothing here pushes.",
                "set `persist-credentials: false`.",
            ),
        ],
        [
            _finding(
                "medium",
                "CICD-SEC-1 Insufficient Flow Control Mechanisms",
                ".github/workflows/preview.yml:13",
                "any fork PR that passes CI is published to the preview site "
                "with no environment protection rule or maintainer approval.",
                "add an `environment:` with required reviewers.",
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
                "Long Method (Bloaters)",
                "billing/invoice.py:8",
                "`generate_invoice` validates, prices, discounts, taxes, renders "
                "and delivers in one ~55-line function.",
                "Extract Method: pull each step into its own function.",
            )
        ],
        [
            _finding(
                "low",
                "Magic Number (Bloaters)",
                "billing/invoice.py:28",
                "the loyalty rate 0.05, the 10000 threshold and the 50.0 bonus "
                "are unexplained literals.",
                "extract them into named constants next to `TAX_RATES`.",
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
                "critical",
                "Open security group",
                "infra/network.tf:18",
                "the new ingress rule allows SSH from 0.0.0.0/0, exposing port 22 "
                "to the whole internet.",
                "restrict the CIDR to the bastion or VPN range.",
            )
        ],
        [
            _finding(
                "low",
                "Hygiene",
                "infra/network.tf:5",
                "the rules are inline `ingress` blocks, which fight any "
                "standalone rule resources for the same group on every apply.",
                "define them as `aws_vpc_security_group_ingress_rule` resources.",
            )
        ],
    ),
    "logging": (
        [
            _finding(
                "critical",
                "Secret in log",
                "auth/session.py:14",
                "the raw bearer token is interpolated into the auth-failure "
                "warning, so anyone with log access can replay the credential.",
                "log the user id and a token fingerprint instead.",
            )
        ],
        [
            _finding(
                "high",
                "Log injection",
                "auth/session.py:14",
                "the token comes from the request and is interpolated unescaped, "
                "so CR/LF in it forges log lines.",
                "pass it as a %-style argument and escape control characters.",
            )
        ],
    ),
    "migration-review": (
        [
            _finding(
                "critical",
                "Blocking lock",
                "db/migrate/20260704120000_add_index_to_events.rb:3",
                "`add_index` builds the index non-concurrently, holding a lock "
                "that stops writes to the ~200M-row events table for the build.",
                "use `algorithm: :concurrently` with `disable_ddl_transaction!`.",
            )
        ],
        [
            _finding(
                "low",
                "Reversibility",
                "db/migrate/20260704120000_add_index_to_events.rb:3",
                "re-running the migration after a failed deploy errors if the "
                "index already exists.",
                "pass `if_not_exists: true`.",
            )
        ],
    ),
    "resilience-review": (
        [
            _finding(
                "high",
                "Missing timeout",
                "services/client.py:13",
                "`requests.get` is called without one, so a stalled recs service "
                "holds the request thread indefinitely.",
                "pass `timeout=(3, 10)`.",
            )
        ],
        [
            _finding(
                "medium",
                "No graceful degradation",
                "services/client.py:13",
                "recommendations are optional, but if the recs service errors or "
                "hangs the whole page fails.",
                "catch the error and return an empty list.",
            )
        ],
    ),
    "security-review": (
        [
            _finding(
                "high",
                "V8 Authorization",
                "app/orders.py:18",
                "`get_invoice` loads any order by ID without scoping it to the "
                "signed-in user, so any caller can read another customer's "
                "invoice (IDOR).",
                "scope the query to the session's user, as `get_order` does.",
            )
        ],
        [
            _finding(
                "low",
                "V16 Security Logging and Error Handling",
                "app/orders.py:10",
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
