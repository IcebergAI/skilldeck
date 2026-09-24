"""Unit tests for the eval scorer and runner in ``evals/run_evals.py``.

Synthetic reports and a stand-in agent only -- no paid API calls.
"""

import shlex
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import run_evals  # loaded from evals/run_evals.py by conftest.py


def _plant(file="auth/session.py", keywords=("secret",), **extra):
    return run_evals.Plant(file=file, keywords=tuple(keywords), **extra)


def _fixture(*plants, max_findings=5):
    return run_evals.Fixture(
        path=Path("fixture"),
        skill="logging",
        plants=tuple(plants),
        max_findings=max_findings,
    )


def _finding(location, issue, severity="high", marker="-", kind="Issue kind"):
    return (
        f"{marker} **[{severity}] {kind}** — `{location}`\n"
        f"  **Issue:** {issue}\n"
        "  **Fix:** remove it.\n"
    )


HEADER = "Reviewed main..HEAD (1 file): 1 finding, worst high.\n\n"


# -- plant matching ------------------------------------------------------------


def test_a_finding_naming_the_file_and_a_keyword_satisfies_the_plant():
    report = HEADER + _finding("auth/session.py:14", "the token is a secret")
    assert run_evals.score(_fixture(_plant()), report) == ([], True)


def test_basename_or_relative_path_locates_the_plant():
    fixture = _fixture(_plant())
    for location in ("session.py:14", "auth/session.py", "./auth/session.py:3"):
        report = _finding(location, "a secret is logged")
        assert run_evals.score(fixture, report)[1], location


def test_a_negative_mention_of_the_file_does_not_satisfy_the_plant():
    # the file and the keyword both appear -- but never in the same finding
    report = (
        "Reviewed main..HEAD: `auth/session.py` logs no secret; it is clean.\n\n"
        + _finding("auth/audit.py:3", "the audit event omits the actor", "low")
    )
    problems, passed = run_evals.score(_fixture(_plant()), report)
    assert not passed
    assert problems == [
        "missed plant: auth/session.py (need a finding naming the file and one "
        "of ['secret'])"
    ]


@pytest.mark.parametrize(
    "trailer",
    [
        "\n`auth/session.py`: no secrets logged, clean.\n",
        "\n**Summary:** I checked auth/session.py; no secret is logged.\n",
        "\n---\nNo secret reaches the log in auth/session.py.\n",
        "***\nNo secret reaches the log in auth/session.py.\n",
        "\nSummary\n=======\nauth/session.py handles the secret correctly.\n",
        "- auth/session.py: no secret logged.\n",
    ],
    ids=["line", "bold-label", "thematic-break", "stars", "setext", "sibling-item"],
)
def test_text_after_the_last_finding_is_not_part_of_it(trailer):
    # the #106 example: a clean verdict on the planted file, after the last
    # finding and without a heading, must not satisfy the plant
    report = HEADER + _finding("auth/audit.py:3", "the actor is missing", "low")
    report += trailer
    (finding,) = run_evals.parse_findings(report)
    assert "session.py" not in finding.text
    assert not run_evals.score(_fixture(_plant()), report)[1]


def test_indented_paragraphs_and_unindented_fields_stay_in_the_finding():
    report = textwrap.dedent(
        """\
        1. **[high] Secret in log** — `auth/audit.py:3`

           A second paragraph, indented under the numbered bullet.

        **Issue:** an unindented Issue line after a blank line.

        **Fix:** and an unindented Fix line.
          - a nested bullet
        """
    )
    (finding,) = run_evals.parse_findings(report)
    for text in ("second paragraph", "unindented Issue", "unindented Fix", "nested"):
        assert text in finding.text


def test_file_and_keyword_split_across_findings_do_not_count():
    report = _finding("auth/session.py:14", "logs the user id") + _finding(
        "auth/audit.py:3", "a secret is logged"
    )
    assert not run_evals.score(_fixture(_plant()), report)[1]


@pytest.mark.parametrize(
    ("keyword", "text"),
    [
        ("git", "the package now installs from github"),
        ("state", "the SQL statement is built by hand"),
        ("lock", "the lockfile is out of date"),
        ("lock", "the block is too long"),
        ("timeout", "timeouts are configured"),
    ],
)
def test_a_keyword_only_matches_as_a_whole_word(keyword, text):
    fixture = _fixture(_plant(file="requirements.txt", keywords=[keyword]))
    report = _finding("requirements.txt:3", text)
    problems, passed = run_evals.score(fixture, report)
    assert not passed and problems[0].startswith("missed plant")


def test_keywords_are_case_insensitive_and_phrases_span_line_wraps():
    fixture = _fixture(_plant(file="billing/invoice.py", keywords=["Long Method"]))
    report = _finding(
        "billing/invoice.py:8", "generate_invoice is a textbook long\n  method"
    )
    assert run_evals.score(fixture, report)[1]


def test_phrase_keywords_match_across_inline_markdown():
    fixture = _fixture(_plant(file="tests/test_d.py", keywords=["no assert"]))
    for text in ("has no `assert`", "has **no** assert", "has no\n  `assert`"):
        assert run_evals.score(fixture, _finding("tests/test_d.py:8", text))[1], text
    assert not run_evals.mentions("no `assertion`", "no assert")


def test_keywords_with_punctuation_match_whole():
    fixture = _fixture(_plant(file=".gitlab-ci.yml", keywords=["CICD-SEC-4"]))
    assert run_evals.score(fixture, _finding(".gitlab-ci.yml:9", "see CICD-SEC-4"))[1]
    assert not run_evals.score(
        fixture, _finding(".gitlab-ci.yml:9", "see CICD-SEC-40")
    )[1]


def test_two_plants_in_one_file_need_two_findings():
    injection = _plant(file=".gitlab-ci.yml", keywords=["injection"])
    runner = _plant(file=".gitlab-ci.yml", keywords=["runner"])
    fixture = _fixture(injection, runner)

    both_in_one = _finding(".gitlab-ci.yml:12", "injection, and the runner too")
    problems, passed = run_evals.score(fixture, both_in_one)
    assert not passed
    assert problems == [
        "missed plant: .gitlab-ci.yml (its matching finding already accounts for "
        "another plant; each plant needs its own finding)"
    ]

    separate = _finding(".gitlab-ci.yml:12", "script injection") + _finding(
        ".gitlab-ci.yml:20", "the runner is exposed"
    )
    assert run_evals.score(fixture, separate) == ([], True)


def test_matching_reassigns_findings_rather_than_choosing_greedily():
    # finding 0 satisfies both plants, finding 1 only the first: a greedy
    # first-come assignment would give finding 0 to plant 0 and strand plant 1
    first = _plant(file="app/sso.py", keywords=["state", "CSRF"])
    second = _plant(file="app/sso.py", keywords=["sub"])
    report = _finding("app/sso.py:29", "no state, and identity is not sub") + (
        _finding("app/sso.py:20", "login CSRF")
    )
    assert run_evals.match_plants(
        (first, second), run_evals.parse_findings(report)
    ) == {0: 1, 1: 0}
    assert run_evals.score(_fixture(first, second), report) == ([], True)


def test_locators_place_a_finding_whose_location_is_not_a_file():
    plant = _plant(
        file="requirements.txt", keywords=["confusion"], locators=("corp-auth",)
    )
    report = _finding("corp-auth ~=2.4", "dependency confusion via extra index")
    assert run_evals.score(_fixture(plant), report)[1]
    unlocated = _plant(file="requirements.txt", keywords=["confusion"])
    assert not run_evals.score(_fixture(unlocated), report)[1]


# -- severity ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "passes"),
    [
        ("critical", True),
        ("high", True),
        ("High", True),
        ("medium", False),
        ("low", False),
        ("severe", False),  # not on the scale: can't prove it is high enough
    ],
)
def test_min_severity_is_enforced(severity, passes):
    fixture = _fixture(_plant(min_severity="high"))
    report = _finding("auth/session.py:14", "a secret is logged", severity)
    problems, passed = run_evals.score(fixture, report)
    assert passed is passes
    if not passes:
        assert problems == [
            f"missed plant: auth/session.py (reported as [{severity.lower()}], "
            "below min-severity high)"
        ]


def test_without_min_severity_any_severity_counts():
    report = _finding("auth/session.py:14", "a secret is logged", "low")
    assert run_evals.score(_fixture(_plant()), report)[1]


# -- report parsing ------------------------------------------------------------


@pytest.mark.parametrize("marker", ["-", "*", "1.", "1)", "12.", "  -"])
def test_finding_bullet_markers_parse(marker):
    report = HEADER + _finding("auth/session.py:14", "a secret", marker=marker)
    findings = run_evals.parse_findings(report)
    assert [f.severity for f in findings] == ["high"]
    assert run_evals.score(_fixture(_plant()), report)[1]


def test_non_finding_bullets_are_not_findings():
    report = "- **Issue:** not a finding\n- plain bullet\n**[high]** no marker\n"
    assert run_evals.parse_findings(report) == []


def test_a_finding_spans_to_the_next_finding_or_heading():
    report = textwrap.dedent(
        """\
        ## Findings

        - **[high] A** — `a.py:1`
          **Issue:** first.

          **Fix:** blank lines stay inside the finding.
        * **[low] B** — `b.py:2`
          **Issue:** second.

        ## Summary

        auth/session.py leaks a secret.
        """
    )
    findings = run_evals.parse_findings(report)
    assert [f.severity for f in findings] == ["high", "low"]
    assert "blank lines stay inside" in findings[0].text
    assert "b.py" not in findings[0].text
    assert "Summary" not in findings[1].text
    # the summary belongs to no finding, so it can't satisfy a plant
    assert not run_evals.score(_fixture(_plant()), report)[1]


def test_a_comment_in_a_fenced_fix_is_not_a_heading():
    report = textwrap.dedent(
        """\
        - **[critical] Blocking lock** — `db/migrate/1_add_index.rb:3`
          **Issue:** builds the index without the concurrent option.
          **Fix:**
          ```ruby
          # build it without blocking writes
          disable_ddl_transaction!
          ```
          This keeps writes flowing on the events table.
        """
    )
    (finding,) = run_evals.parse_findings(report)
    assert "keeps writes flowing" in finding.text


def test_a_report_wrapped_in_a_code_fence_still_parses():
    report = "```markdown\n" + _finding("auth/session.py:14", "a secret") + "```\n"
    assert len(run_evals.parse_findings(report)) == 1
    assert run_evals.score(_fixture(_plant()), report)[1]


def test_a_summary_after_a_wrapping_fence_is_not_part_of_the_last_finding():
    report = (
        "```markdown\n"
        + HEADER
        + _finding("auth/audit.py:3", "the actor is missing", "low")
        + "```\n\n## Summary\n`auth/session.py` never logs a secret.\n"
    )
    (finding,) = run_evals.parse_findings(report)
    assert "session.py" not in finding.text
    assert not run_evals.score(_fixture(_plant()), report)[1]


def test_a_fix_fence_inside_a_wrapped_report_does_not_close_the_wrapper():
    report = textwrap.dedent(
        """\
        ```markdown
        - **[high] Secret in log** — `auth/session.py:14`
          **Issue:** the token is logged.
          **Fix:**
          ```
          # log the user id, not the secret
          ```
        - **[low] Missing event** — `auth/audit.py:3`
          **Issue:** no logout event.
        ```
        ## Summary
        auth/audit.py is otherwise fine.
        """
    )
    first, second = run_evals.parse_findings(report)
    assert "not the secret" in first.text
    assert "Summary" not in second.text


def test_a_fence_closes_only_on_a_run_at_least_as_long():
    # a ```` fence showing markdown that itself contains ``` must not end
    # early and swallow the findings after it
    report = textwrap.dedent(
        """\
        - **[low] A** — `a.py:1`
          **Fix:**
          ````markdown
          ```python
          ````
        - **[low] B** — `b.py:2`
          **Issue:** second.
        - **[low] C** — `c.py:3`
          **Issue:** ```inline code``` is not a fence.
        - **[low] D** — `d.py:4`
          **Issue:** fourth.
        """
    )
    assert len(run_evals.parse_findings(report)) == 4


def test_an_unclosed_fence_ends_at_the_next_finding():
    report = textwrap.dedent(
        """\
        - **[high] A** — `a.py:1`
          **Fix:**
          ```python
          log.info("user %s", user_id)
        - **[critical] B** — `b.py:2`
          **Issue:** second.
        """
    )
    assert [f.severity for f in run_evals.parse_findings(report)] == [
        "high",
        "critical",
    ]


def test_zero_parsed_findings_flags_format_drift():
    report = "Reviewed main..HEAD: auth/session.py logs a secret (high).\n"
    problems, passed = run_evals.score(_fixture(_plant()), report)
    assert not passed
    assert len(problems) == 1
    assert problems[0].startswith("no findings parsed — output format drift?")


@pytest.mark.parametrize(
    "line",
    [
        "1. [critical] V5 Validation — `app/documents.py:20`",
        "- [high] V8 Authorization — `app/documents.py:21`",
        "- **High — V4 API** — `app/documents.py:16`",
        "* **critical** — `app/documents.py:20`",
        "2) Medium: no rate limit on `app/documents.py:16`",
    ],
    ids=["numbered", "no-bold", "no-brackets", "bold-word", "colon"],
)
def test_findings_in_a_drifted_format_fail_even_a_clean_fixture(line):
    # unparsed, they would count as zero findings and pass max-findings
    report = HEADER + line + "\n  **Issue:** something.\n"
    problems, passed = run_evals.score(_fixture(max_findings=1), report)
    assert not passed
    assert problems == [
        "1 finding(s) not in the '- **[severity] ...' format — output format "
        f"drift? (first: {line!r})"
    ]


def test_ordinary_list_items_are_not_drift():
    report = HEADER + textwrap.dedent(
        """\
        - High-level: the change only removes string-built SQL.
        - Low risk overall; no findings.
        - No high-severity issues.
        """
    )
    assert run_evals.score(_fixture(max_findings=0), report) == ([], True)


def test_empty_report_fails():
    for fixture in (_fixture(_plant()), _fixture(max_findings=0)):
        problems, passed = run_evals.score(fixture, "  \n")
        assert not passed
        assert problems == ["empty report: the agent wrote nothing to stdout"]


# -- false-positive pressure and clean fixtures --------------------------------


def test_too_many_findings_fails():
    hit = _finding("auth/session.py:14", "a secret")
    noise = _finding("auth/other.py:1", "nit", "low")
    fixture = _fixture(_plant(), max_findings=2)
    assert run_evals.score(fixture, hit + noise)[1]
    problems, passed = run_evals.score(fixture, hit + noise * 2)
    assert not passed
    assert problems == ["too many findings: 3 > max 2 (false-positive pressure)"]


def test_clean_fixture_passes_a_clean_report_and_fails_on_noise():
    strict = _fixture(max_findings=0)
    clean = "Reviewed main..HEAD (1 file): no findings — the change is clean.\n"
    assert run_evals.score(strict, clean) == ([], True)
    nit = HEADER + _finding("app/documents.py:20", "consider a rate limit", "low")
    problems, passed = run_evals.score(strict, nit)
    assert not passed
    assert problems == ["too many findings: 1 > max 0 (false-positive pressure)"]

    tolerant = _fixture(max_findings=1)
    assert run_evals.score(tolerant, nit)[1]
    assert not run_evals.score(tolerant, nit + nit)[1]


# -- fixture loading -----------------------------------------------------------


def _write_expected(tmp_path, text):
    (tmp_path / "expected.yaml").write_text(textwrap.dedent(text), encoding="utf-8")
    return tmp_path


def test_load_fixture_reads_optional_plant_fields(tmp_path):
    path = _write_expected(
        tmp_path,
        """\
        skill: dependency-review
        plants:
          - file: requirements.txt
            keywords: [confusion, public index]
            min-severity: high
            locators: [corp-auth-client]
        max-findings: 3
        """,
    )
    (plant,) = run_evals.load_fixture(path).plants
    assert plant.keywords == ("confusion", "public index")
    assert plant.min_severity == "high"
    assert plant.locators == ("corp-auth-client",)


def test_load_fixture_accepts_a_clean_diff(tmp_path):
    path = _write_expected(tmp_path, "skill: logging\nplants: []\nmax-findings: 0\n")
    fixture = run_evals.load_fixture(path)
    assert fixture.plants == ()
    assert fixture.max_findings == 0


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "skill: x\nplants: []\nmax-findings: 1\nnotes: y\n",
            "unknown key(s) ['notes']",
        ),
        ("skill: x\nplants: []\n", "missing required key(s) ['max-findings']"),
        ("skill: x\nplants: {}\nmax-findings: 1\n", "plants must be a list"),
        ("skill: x\nplants: []\nmax-findings: -1\n", "non-negative integer"),
        ("skill: x\nplants: []\nmax-findings: yes\n", "non-negative integer"),
        ("- just a list\n", "expected a YAML mapping"),
        (
            "skill: x\nplants:\n  - {file: a.py, keywords: [k], severity: high}\n"
            "max-findings: 1\n",
            "unknown key(s) ['severity']",
        ),
        (
            "skill: x\nplants:\n  - {file: a.py, keywords: [k], min-severity: severe}\n"
            "max-findings: 1\n",
            "min-severity must be one of",
        ),
        (
            "skill: x\nplants:\n  - {file: a.py, keywords: []}\nmax-findings: 1\n",
            "expected a non-empty list of strings",
        ),
        (
            "skill: x\nplants:\n  - {file: a.py, keywords: [22]}\nmax-findings: 1\n",
            "expected a non-empty string",
        ),
        (
            "skill: x\nplants:\n  - {file: a.py, keywords: [k]}\n"
            "  - {file: b.py, keywords: [k]}\nmax-findings: 1\n",
            "below the number of plants",
        ),
    ],
)
def test_load_fixture_rejects_invalid_expected_yaml(tmp_path, text, message):
    path = _write_expected(tmp_path, text)
    with pytest.raises(run_evals.FixtureError) as excinfo:
        run_evals.load_fixture(path)
    assert message in str(excinfo.value)


# -- agent runs ----------------------------------------------------------------


def _fake_subprocess_run(monkeypatch, result=None, raises=None):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if raises is not None:
            raise raises
        return result

    monkeypatch.setattr(run_evals.subprocess, "run", fake_run)
    return calls


def test_run_agent_substitutes_the_prompt_and_keeps_streams_apart(
    monkeypatch, tmp_path
):
    calls = _fake_subprocess_run(
        monkeypatch,
        subprocess.CompletedProcess([], 0, stdout="report", stderr="warning"),
    )
    run = run_evals.run_agent("claude -p {prompt}", "review it", tmp_path, 60)
    assert calls[0][0] == ["claude", "-p", "review it"]
    assert calls[0][1]["cwd"] == tmp_path
    assert run == run_evals.AgentRun("report", "warning", 0, 60)


def test_non_zero_exit_fails_the_fixture_without_scoring(monkeypatch, tmp_path):
    good_report = _finding("auth/session.py:14", "a secret")
    _fake_subprocess_run(
        monkeypatch,
        subprocess.CompletedProcess([], 2, stdout=good_report, stderr="rate limited"),
    )
    run = run_evals.run_agent("claude -p {prompt}", "p", tmp_path, 60)
    assert run.returncode == 2
    assert run.stderr == "rate limited"
    problems, passed = run_evals.evaluate(_fixture(_plant()), run)
    assert not passed
    assert problems == ["agent exited with status 2"]


def test_timeout_fails_the_fixture(monkeypatch, tmp_path):
    _fake_subprocess_run(
        monkeypatch,
        raises=subprocess.TimeoutExpired(
            ["claude"], 5, output=b"- **[high] partial", stderr=b"still thinking"
        ),
    )
    run = run_evals.run_agent("claude -p {prompt}", "p", tmp_path, 5)
    assert run.returncode is None
    assert (run.stdout, run.stderr) == ("- **[high] partial", "still thinking")
    assert run_evals.evaluate(_fixture(_plant()), run) == (
        ["agent timed out after 5s"],
        False,
    )


def test_stderr_is_not_scored():
    run = run_evals.AgentRun(
        stdout="Reviewed main..HEAD: see below.\n",
        stderr=_finding("auth/session.py:14", "a secret"),
        returncode=0,
        timeout=60,
    )
    problems, passed = run_evals.evaluate(_fixture(_plant()), run)
    assert not passed
    assert problems[0].startswith("no findings parsed")


def test_missing_agent_command_is_a_clean_error(monkeypatch, tmp_path):
    _fake_subprocess_run(monkeypatch, raises=FileNotFoundError())
    with pytest.raises(SystemExit, match="agent command not found"):
        run_evals.run_agent("no-such-agent {prompt}", "p", tmp_path, 5)


# -- adapters, prompts, and fixture selection ----------------------------------


def test_prompt_names_the_installed_skill_for_the_adapter():
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    claude = run_evals.build_prompt(fixture)
    assert "using the logging skill installed at .claude/skills/logging/SKILL.md" in (
        claude
    )
    assert ".agents/skills/logging/SKILL.md" in run_evals.build_prompt(fixture, "codex")


def test_prepare_repo_installs_through_the_chosen_adapter(tmp_path):
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    repo = run_evals.prepare_repo(fixture, tmp_path, "kiro")
    assert (repo / run_evals.skill_path(fixture, "kiro")).is_file()
    assert not (repo / ".claude").exists()


def test_select_fixtures_by_skill_or_directory():
    names = {f.name for f in run_evals.select_fixtures("authentication-review")}
    assert names == {"authentication-review", "authentication-review-saml"}
    (saml,) = run_evals.select_fixtures("authentication-review-saml")
    assert saml.skill == "authentication-review"
    assert run_evals.select_fixtures("no-such-skill") == []


# -- end to end, with a stand-in agent ----------------------------------------


def _stand_in_agent(tmp_path, body):
    script = tmp_path / "agent.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{prompt}}"


def _main(monkeypatch, tmp_path, *argv):
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setattr(run_evals.tempfile, "mkdtemp", lambda **_: str(workdir))
    return run_evals.main(list(argv)), workdir


def test_main_repeats_each_fixture_and_reports_the_pass_rate(
    monkeypatch, tmp_path, capsys
):
    agent = _stand_in_agent(
        tmp_path,
        """\
        import sys
        assert ".claude/skills/logging/SKILL.md" in sys.argv[1]
        print("Reviewed main..HEAD (1 file): 1 finding, critical.")
        print("- **[critical] Secret in log** — `auth/session.py:14`")
        print("  **Issue:** the bearer token, a credential, is logged.")
        print("  **Fix:** log the user id only.")
        """,
    )
    status, workdir = _main(
        monkeypatch,
        tmp_path,
        *("--skill", "logging", "--agent-cmd", agent, "--repeat", "2"),
    )
    out = capsys.readouterr().out
    assert status == 0, out
    assert "PASS  logging #1" in out and "PASS  logging #2" in out
    assert "2/2 (100%)  logging" in out
    assert not workdir.exists()  # cleaned up when every run passes


def test_main_reports_a_failing_agent_with_its_stderr(monkeypatch, tmp_path, capsys):
    agent = _stand_in_agent(
        tmp_path,
        """\
        import sys
        print("partial output")
        print("upstream overloaded", file=sys.stderr)
        sys.exit(3)
        """,
    )
    status, workdir = _main(
        monkeypatch, tmp_path, "--skill", "logging", "--agent-cmd", agent
    )
    out = capsys.readouterr().out
    assert status == 1
    assert "FAIL  logging" in out
    assert "agent exited with status 3" in out
    assert "upstream overloaded" in out
    report = workdir / "logging" / "report.txt"
    assert report.read_text(encoding="utf-8") == "partial output\n"
    assert (workdir / "logging" / "stderr.txt").is_file()


def test_main_rejects_an_unknown_fixture(capsys):
    assert run_evals.main(["--skill", "no-such-skill"]) == 2
    assert "no fixture for 'no-such-skill'" in capsys.readouterr().err


def test_remove_tree_deletes_read_only_files(tmp_path):
    # git writes its object files read-only; Windows refuses to delete those
    # unless the read-only bit is cleared first
    tree = tmp_path / "work" / "repo" / ".git" / "objects" / "ab"
    tree.mkdir(parents=True)
    obj = tree / "cdef"
    obj.write_text("blob", encoding="utf-8")
    obj.chmod(stat.S_IREAD)
    run_evals.remove_tree(tmp_path / "work")
    assert not (tmp_path / "work").exists()
