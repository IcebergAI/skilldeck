"""Tests for eval run records, harness presets, budgets, dry runs and replay.

Everything here uses stand-in agents (a Python script in the harness's place)
-- no agent CLI, credentials or paid API calls.
"""

import itertools
import json
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import run_evals  # loaded from evals/run_evals.py by conftest.py

from skilldeck import __version__
from skilldeck.provenance import canonical_json, sha256_text

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads(
    (ROOT / "evals" / "run-record.schema.json").read_text(encoding="utf-8")
)
CONTENT_MANIFEST = json.loads(
    (ROOT / "src" / "skilldeck" / "_content_manifest.json").read_text(encoding="utf-8")
)

# a report that passes the logging fixture
PASSING_AGENT = """\
    import sys
    print("Reviewed main..HEAD (1 file): 1 finding, high.")
    print("- **[high] Log injection** — `auth/session.py:15`")
    print("  **Issue:** a CR/LF in the username forges log lines.")
    print("  **Fix:** escape control characters.")
"""


# -- a minimal JSON Schema validator -------------------------------------------
#
# Just the draft 2020-12 keywords evals/run-record.schema.json uses, so the
# schema is checked without a runtime or dev dependency. An unsupported
# keyword fails loudly rather than being silently ignored.

_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$defs",
        "$ref",
        "title",
        "description",
        "type",
        "const",
        "enum",
        "anyOf",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "pattern",
        "minimum",
    }
)


def _is_type(value, kind):
    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "null": value is None,
        "integer": number and isinstance(value, int),
        "number": number,
    }[kind]


def _same(a, b):
    # JSON equality: 1 is not true
    return type(a) is type(b) and a == b


def schema_errors(value, schema=SCHEMA, where="$"):
    unknown = set(schema) - _KEYWORDS
    assert not unknown, f"validator does not support {sorted(unknown)}"
    errors = []
    if "$ref" in schema:
        prefix = "#/$defs/"
        assert schema["$ref"].startswith(prefix)
        target = SCHEMA["$defs"][schema["$ref"].removeprefix(prefix)]
        errors += schema_errors(value, target, where)
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, kind) for kind in kinds):
            return [*errors, f"{where}: {value!r} is not of type {kinds}"]
    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{where}: {value!r} is not {schema['const']!r}")
    if "enum" in schema and not any(_same(value, v) for v in schema["enum"]):
        errors.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if "anyOf" in schema and all(
        schema_errors(value, branch, where) for branch in schema["anyOf"]
    ):
        errors.append(f"{where}: {value!r} matches no anyOf branch")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [
            f"{where}: missing {key!r}"
            for key in schema.get("required", ())
            if key not in value
        ]
        for key, item in value.items():
            if key in properties:
                errors += schema_errors(item, properties[key], f"{where}.{key}")
            elif schema.get("additionalProperties", True) is False:
                errors.append(f"{where}: unexpected {key!r}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += schema_errors(item, schema["items"], f"{where}[{i}]")
    if (
        isinstance(value, str)
        and "pattern" in schema
        and not re.search(schema["pattern"], value)
    ):
        errors.append(f"{where}: {value!r} does not match {schema['pattern']!r}")
    if _is_type(value, "number") and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{where}: {value!r} is below {schema['minimum']}")
    return errors


# -- helpers -------------------------------------------------------------------


def _stand_in_agent(tmp_path, body, name="agent.py"):
    script = tmp_path / name
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{prompt}}"


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    """Return ``run(*argv) -> (status, workdir)``, a fresh work dir per call."""
    counter = itertools.count(1)

    def mkdtemp(**_):
        workdir = tmp_path / f"work-{next(counter)}"
        workdir.mkdir()
        return str(workdir)

    monkeypatch.setattr(run_evals.tempfile, "mkdtemp", mkdtemp)

    def run(*argv):
        before = set(tmp_path.glob("work-*"))
        status = run_evals.main(list(argv))
        (workdir,) = set(tmp_path.glob("work-*")) - before or {None}
        return status, workdir

    return run


def _record(workdir):
    text = (workdir / run_evals.RECORD_NAME).read_text(encoding="utf-8")
    return text, json.loads(text)


@pytest.fixture
def no_subprocess(monkeypatch):
    """Fail the test if anything -- an agent, git, a version probe -- runs."""

    def forbidden(cmd, **_):
        raise AssertionError(f"unexpected subprocess: {cmd}")

    monkeypatch.setattr(run_evals.subprocess, "run", forbidden)
    monkeypatch.setattr(
        run_evals.tempfile,
        "mkdtemp",
        lambda **_: pytest.fail("a dry run must not create a work dir"),
    )


# -- the run record ------------------------------------------------------------


def test_record_captures_every_field_in_a_deterministic_order(run_main, tmp_path):
    agent = _stand_in_agent(tmp_path, PASSING_AGENT)
    status, workdir = run_main(
        "--skill", "logging", "--agent-cmd", agent, "--repeat", "2"
    )
    assert status == 0
    text, record = _record(workdir)
    assert schema_errors(record) == []
    # sorted keys, two-space indent, one final newline -- byte-stable
    assert text == canonical_json(record)
    assert (workdir / run_evals.RECORD_NAME).read_bytes().count(b"\r") == 0

    assert record["schema_version"] == 1
    assert record["status"] == "complete"
    assert record["skilldeck"]["version"] == __version__
    assert record["skilldeck"]["runner_sha256"] == run_evals.runner_digest()
    assert record["harness"] == {
        "name": "custom",
        "command": agent,
        "model": None,
        "version": None,
        "version_command": None,
    }
    assert record["adapter"] == "claude"
    assert record["config"] == {
        "repeat": 2,
        "timeout_s": 600,
        "max_runs": 50,
        "jobs": 1,
        "include_reports": False,
        "replay_of": None,
    }

    (fixture,) = record["fixtures"]
    (manifest,) = [s for s in CONTENT_MANIFEST["skills"] if s["name"] == "logging"]
    assert fixture["name"] == "logging"
    assert fixture["digest"] == run_evals.fixture_digest(run_evals.FIXTURES / "logging")
    assert fixture["skill"] == {
        "name": "logging",
        "version": manifest["version"],
        "canonical_sha256": manifest["canonical_sha256"],
        "rendered_sha256": manifest["claude_rendered_sha256"],
    }
    assert ".claude/skills/logging/SKILL.md" in fixture["prompt"]
    assert [run["attempt"] for run in fixture["runs"]] == [1, 2]
    for run in fixture["runs"]:
        assert run["status"] == "passed" and run["passed"] is True
        assert run["problems"] == []
        assert run["exit_code"] == 0 and run["timed_out"] is False
        assert run["finding_count"] == 1
        assert run["duration_s"] >= 0
        assert run["usage"] is None and run["cost_usd"] is None
        assert run["raw"] is None
        # raw output stays beside the record, referenced by a relative path
        report = workdir / run["artifacts"]["report"]
        assert "Log injection" in report.read_text(encoding="utf-8")
        assert (workdir / run["artifacts"]["stderr"]).is_file()
        assert "\\" not in run["artifacts"]["report"]
    assert "Log injection" not in text
    assert record["summary"] == {
        "planned": 2,
        "attempted": 2,
        "passed": 2,
        "failed": 0,
        "not_run": 0,
    }
    # every run passed: the repos go, the record and raw output stay
    assert not (workdir / "repos").exists()


def test_include_reports_embeds_raw_output(run_main, tmp_path):
    agent = _stand_in_agent(tmp_path, PASSING_AGENT)
    status, workdir = run_main(
        "--skill", "logging", "--agent-cmd", agent, "--include-reports"
    )
    assert status == 0
    _, record = _record(workdir)
    assert schema_errors(record) == []
    assert record["config"]["include_reports"] is True
    (run,) = record["fixtures"][0]["runs"]
    assert "Log injection" in run["raw"]["report"]
    assert run["raw"]["stderr"] == ""


def test_a_failing_agent_is_recorded_with_its_exit_code(run_main, tmp_path, capsys):
    agent = _stand_in_agent(
        tmp_path,
        """\
        import sys
        print("upstream overloaded", file=sys.stderr)
        sys.exit(3)
        """,
    )
    status, workdir = run_main("--skill", "logging", "--agent-cmd", agent)
    assert status == 1
    assert "upstream overloaded" in capsys.readouterr().out
    text, record = _record(workdir)
    assert schema_errors(record) == []
    (run,) = record["fixtures"][0]["runs"]
    assert run["status"] == "agent_failed" and run["passed"] is False
    assert run["exit_code"] == 3
    assert run["problems"] == ["agent exited with status 3"]
    assert "upstream overloaded" not in text  # stderr stays in its artifact
    stderr = workdir / run["artifacts"]["stderr"]
    assert "upstream overloaded" in stderr.read_text(encoding="utf-8")
    assert (workdir / "repos").is_dir()  # kept for inspection on failure
    assert record["summary"]["failed"] == 1


def test_a_timeout_is_recorded(run_main, monkeypatch, tmp_path):
    def timed_out(agent_cmd, prompt, repo, timeout, model=None):
        return run_evals.AgentRun("- **[high] partial", "", None, timeout)

    monkeypatch.setattr(run_evals, "run_agent", timed_out)
    status, workdir = run_main(
        "--skill", "logging", "--agent-cmd", "agent {prompt}", "--timeout", "7"
    )
    assert status == 1
    _, record = _record(workdir)
    assert schema_errors(record) == []
    (run,) = record["fixtures"][0]["runs"]
    assert run["status"] == "timed_out" and run["timed_out"] is True
    assert run["exit_code"] is None
    assert run["problems"] == ["agent timed out after 7s"]
    assert record["config"]["timeout_s"] == 7


def test_a_missing_agent_command_is_recorded_and_stops_the_rest(run_main, capsys):
    status, workdir = run_main(
        "--skill",
        "authentication-review",
        "--agent-cmd",
        "no-such-agent-skilldeck-test {prompt}",
        "--repeat",
        "2",
    )
    assert status == 2
    assert "stopped early: agent command not found" in capsys.readouterr().err
    _, record = _record(workdir)
    assert schema_errors(record) == []
    assert record["status"] == "incomplete"
    runs = [run for f in record["fixtures"] for run in f["runs"]]
    assert [run["status"] for run in runs] == ["error", *["not_run"] * 3]
    assert runs[0]["problems"][0].startswith("agent command not found")
    assert all(run["problems"][0].startswith("not run: ") for run in runs[1:])
    assert record["summary"] == {
        "planned": 4,
        "attempted": 1,
        "passed": 0,
        "failed": 1,
        "not_run": 3,
    }


def test_an_interrupt_still_writes_the_record(run_main, monkeypatch):
    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_evals, "attempt_run", interrupted)
    status, workdir = run_main("--skill", "logging", "--agent-cmd", "a {prompt}")
    assert status == 130
    _, record = _record(workdir)
    assert record["status"] == "incomplete"
    assert record["fixtures"][0]["runs"][0]["problems"] == ["interrupted"]


def test_a_repo_that_cannot_be_built_is_recorded(run_main, monkeypatch):
    def broken(*_args):
        raise subprocess.CalledProcessError(128, ["git", "init"])

    monkeypatch.setattr(run_evals, "prepare_repo", broken)
    status, workdir = run_main("--skill", "logging", "--agent-cmd", "a {prompt}")
    assert status == 1
    _, record = _record(workdir)
    (run,) = record["fixtures"][0]["runs"]
    assert run["status"] == "error"
    assert run["problems"][0].startswith("could not build the review repo")


def test_the_schema_rejects_a_malformed_record(run_main, tmp_path):
    agent = _stand_in_agent(tmp_path, PASSING_AGENT)
    _, workdir = run_main("--skill", "logging", "--agent-cmd", agent)
    _, record = _record(workdir)
    run = record["fixtures"][0]["runs"][0]
    run["report_text"] = "raw"
    del run["exit_code"]
    run["status"] = "maybe"
    record["config"]["jobs"] = True
    assert sorted(schema_errors(record)) == sorted(
        [
            "$.config.jobs: True is not 1",
            "$.fixtures[0].runs[0]: missing 'exit_code'",
            "$.fixtures[0].runs[0]: unexpected 'report_text'",
            "$.fixtures[0].runs[0].status: 'maybe' is not one of "
            "['passed', 'failed', 'agent_failed', 'timed_out', 'error', 'not_run']",
        ]
    )


def _git(*args):
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def test_source_identity_names_this_checkout():
    source = run_evals.source_identity()
    assert source["version"] == __version__
    toplevel = _git("rev-parse", "--show-toplevel")
    if toplevel is None or Path(toplevel).resolve() != ROOT.resolve():
        # not a checkout of its own (an unpacked sdist, say)
        assert source["git_commit"] is None
    else:
        assert source["git_commit"] == _git("rev-parse", "HEAD")
        assert isinstance(source["git_dirty"], bool)


# -- fixture digests -----------------------------------------------------------


def _copy_fixture(tmp_path, name="logging"):
    fixtures = tmp_path / "fixtures"
    shutil.copytree(run_evals.FIXTURES / name, fixtures / name)
    return fixtures


def test_fixture_digest_covers_content_and_paths_but_not_line_endings(tmp_path):
    path = _copy_fixture(tmp_path) / "logging"
    original = run_evals.fixture_digest(path)
    assert original == run_evals.fixture_digest(run_evals.FIXTURES / "logging")

    session = path / "change" / "auth" / "session.py"
    text = session.read_text(encoding="utf-8")
    session.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert run_evals.fixture_digest(path) == original  # a Windows checkout

    session.write_text(text + "# changed\n", encoding="utf-8")
    assert run_evals.fixture_digest(path) != original
    session.write_text(text, encoding="utf-8")
    session.rename(session.with_name("renamed.py"))
    assert run_evals.fixture_digest(path) != original


# -- harness presets -----------------------------------------------------------


def test_the_default_harness_is_claude():
    harness = run_evals.resolve_harness()
    assert harness == run_evals.Harness("claude", "claude -p {prompt}", "claude")
    assert harness.version_command == ["claude", "--version"]
    assert run_evals.agent_argv(harness.command, "P") == ["claude", "-p", "P"]


@pytest.mark.parametrize(
    ("name", "model", "adapter", "argv"),
    [
        ("claude", None, "claude", ["claude", "-p", "P"]),
        ("claude", "opus", "claude", ["claude", "--model", "opus", "-p", "P"]),
        ("codex", None, "codex", ["codex", "exec", "P"]),
        ("codex", "gpt-5", "codex", ["codex", "exec", "--model", "gpt-5", "P"]),
    ],
)
def test_harness_presets_pair_a_command_with_their_adapter(name, model, adapter, argv):
    harness = run_evals.resolve_harness(name, model=model)
    assert harness.name == name
    assert harness.adapter == adapter
    assert harness.model == model
    assert run_evals.agent_argv(harness.command, "P", harness.model) == argv
    assert harness.version_command == [argv[0], "--version"]


def test_agent_cmd_and_adapter_override_a_preset():
    custom = run_evals.resolve_harness(agent_cmd="my-agent {prompt}")
    assert (custom.name, custom.adapter) == ("custom", "claude")
    assert custom.version_command is None

    codex = run_evals.resolve_harness("codex", "codex exec --json {prompt}")
    assert (codex.name, codex.adapter) == ("codex", "codex")
    assert codex.command == "codex exec --json {prompt}"

    kiro = run_evals.resolve_harness("custom", "kiro-cli {prompt}", "kiro")
    assert kiro.adapter == "kiro"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "custom"}, "--harness custom needs --agent-cmd"),
        ({"agent_cmd": "agent"}, "has no {prompt} placeholder"),
        ({"agent_cmd": "agent {prompt}", "model": "m"}, "needs a {model} placeholder"),
        ({"agent_cmd": "agent -m {model} {prompt}"}, "pass --model"),
        ({"agent_cmd": "agent '{prompt}"}, "No closing quotation"),
        ({"name": "claude", "model": " "}, "--model must not be empty"),
        ({"name": "gemini"}, "unknown harness 'gemini'"),
    ],
)
def test_invalid_harness_options_are_config_errors(kwargs, message):
    with pytest.raises(run_evals.ConfigError, match=re.escape(message)):
        run_evals.resolve_harness(**kwargs)


def test_harness_version_is_best_effort():
    version = run_evals.harness_version([sys.executable, "--version"])
    assert version is not None and version.startswith("Python ")
    assert run_evals.harness_version(["no-such-agent-skilldeck-test", "-V"]) is None
    failing = [sys.executable, "-c", "import sys; print('x'); sys.exit(1)"]
    assert run_evals.harness_version(failing) is None
    assert run_evals.harness_version(None) is None


def test_a_preset_harness_records_its_version_and_model(run_main, tmp_path, capsys):
    # --harness codex with a stand-in in its place: the codex adapter installs
    # the skill, the model reaches the command, and the version probe runs
    # the command's own executable
    agent = _stand_in_agent(
        tmp_path,
        """\
        import sys
        model, prompt = sys.argv[1:]
        assert model == "tiny-model", model
        assert ".agents/skills/logging/SKILL.md" in prompt
        print("Reviewed main..HEAD: no findings.")
        """,
    )
    agent = agent.replace("{prompt}", "{model} {prompt}")
    status, workdir = run_main(
        "--skill",
        "logging",
        "--harness",
        "codex",
        "--agent-cmd",
        agent,
        "--model",
        "tiny-model",
    )
    out = capsys.readouterr().out
    assert status == 1, out  # the empty review misses the plant
    assert "harness: codex (adapter codex, model tiny-model)" in out
    _, record = _record(workdir)
    assert schema_errors(record) == []
    assert record["adapter"] == "codex"
    assert record["harness"]["name"] == "codex"
    assert record["harness"]["model"] == "tiny-model"
    assert record["harness"]["version_command"] == [sys.executable, "--version"]
    assert record["harness"]["version"].startswith("Python ")
    (run,) = record["fixtures"][0]["runs"]
    assert run["status"] == "failed"
    assert ".agents/skills/logging/SKILL.md" in record["fixtures"][0]["prompt"]


# -- dry runs and budgets ------------------------------------------------------


def test_dry_run_validates_and_plans_without_running_anything(
    no_subprocess, tmp_path, capsys
):
    marker = tmp_path / "agent-ran"
    agent = _stand_in_agent(tmp_path, f"open({str(marker)!r}, 'w').close()\n")
    status = run_evals.main(["--agent-cmd", agent, "--dry-run", "--repeat", "2"])
    out = capsys.readouterr().out
    assert status == 0, out
    fixtures = [p for p in run_evals.FIXTURES.iterdir() if p.is_dir()]
    runs = 2 * len(fixtures)
    assert (
        f"plan: {len(fixtures)} fixture(s) x 2 repeat(s) = {runs} run(s), "
        "sequential (concurrency 1), max 50"
    ) in out
    for path in fixtures:
        assert f"  {path.name} " in out
    assert "dry run: fixtures are valid; no agent was invoked" in out
    assert not marker.exists()


def _broken_fixtures(tmp_path):
    fixtures = _copy_fixture(tmp_path)
    shutil.rmtree(fixtures / "logging" / "change")
    return fixtures


def test_dry_run_fails_on_an_invalid_fixture(
    no_subprocess, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(run_evals, "FIXTURES", _broken_fixtures(tmp_path))
    assert run_evals.main(["--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "error: logging: missing change/ directory" in err
    assert "plant file auth/session.py is not in change/" in err

    bad = tmp_path / "fixtures" / "logging" / "expected.yaml"
    bad.write_text("skill: logging\nplants: []\n", encoding="utf-8")
    assert run_evals.main(["--dry-run"]) == 2
    assert "missing required key(s) ['max-findings']" in capsys.readouterr().err


def test_dry_run_fails_on_a_skill_the_adapter_cannot_install(
    no_subprocess, monkeypatch, tmp_path, capsys
):
    fixtures = _copy_fixture(tmp_path)
    (fixtures / "logging" / "expected.yaml").write_text(
        "skill: no-such-skill\nplants: []\nmax-findings: 0\n", encoding="utf-8"
    )
    monkeypatch.setattr(run_evals, "FIXTURES", fixtures)
    assert run_evals.main(["--dry-run"]) == 2
    assert "no bundled skill named 'no-such-skill'" in capsys.readouterr().err


def test_max_runs_refuses_before_anything_runs(no_subprocess, capsys):
    argv = ["--skill", "authentication-review", "--repeat", "3", "--max-runs", "5"]
    assert run_evals.main(argv) == 2
    captured = capsys.readouterr()
    assert "6 planned runs exceed --max-runs 5" in captured.err
    assert "= 6 run(s)" in captured.out
    # a dry run reports the same refusal
    assert run_evals.main([*argv, "--dry-run"]) == 2
    assert "exceed --max-runs 5" in capsys.readouterr().err


def test_the_default_budget_caps_a_full_repeated_run(no_subprocess, capsys):
    fixtures = [p for p in run_evals.FIXTURES.iterdir() if p.is_dir()]
    repeat = run_evals.DEFAULT_MAX_RUNS // len(fixtures) + 1
    assert run_evals.main(["--repeat", str(repeat)]) == 2
    assert "exceed --max-runs 50" in capsys.readouterr().err


def test_max_runs_allows_a_plan_within_budget(run_main, tmp_path):
    agent = _stand_in_agent(tmp_path, PASSING_AGENT)
    status, workdir = run_main(
        "--skill",
        "logging",
        "--agent-cmd",
        agent,
        "--repeat",
        "2",
        "--max-runs",
        "2",
    )
    assert status == 0
    _, record = _record(workdir)
    assert record["config"]["max_runs"] == 2


# -- replay --------------------------------------------------------------------


def _first_record(run_main, tmp_path, agent_body=PASSING_AGENT, *extra):
    agent = _stand_in_agent(tmp_path, agent_body)
    status, workdir = run_main("--skill", "logging", "--agent-cmd", agent, *extra)
    assert status in (0, 1)
    return workdir / run_evals.RECORD_NAME


def test_replay_reruns_the_recorded_configuration(run_main, tmp_path):
    path = _first_record(run_main, tmp_path, PASSING_AGENT, "--repeat", "2")
    original = json.loads(path.read_text(encoding="utf-8"))
    status, workdir = run_main("--replay", str(path))
    assert status == 0
    _, replayed = _record(workdir)
    assert schema_errors(replayed) == []
    assert replayed["config"]["replay_of"] == sha256_text(
        path.read_text(encoding="utf-8")
    )
    for key in ("harness", "adapter"):
        assert replayed[key] == original[key]
    assert replayed["config"]["repeat"] == 2
    identity = ("name", "digest", "skill", "prompt")
    assert [{k: f[k] for k in identity} for f in replayed["fixtures"]] == [
        {k: f[k] for k in identity} for f in original["fixtures"]
    ]
    assert replayed["summary"]["passed"] == 2


def test_replay_refuses_a_changed_fixture(run_main, monkeypatch, tmp_path, capsys):
    fixtures = _copy_fixture(tmp_path)
    monkeypatch.setattr(run_evals, "FIXTURES", fixtures)
    path = _first_record(run_main, tmp_path)
    session = fixtures / "logging" / "change" / "auth" / "session.py"
    session.write_text(
        session.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8"
    )
    marker = tmp_path / "agent-ran"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["harness"]["command"] = _stand_in_agent(
        tmp_path, f"open({str(marker)!r}, 'w').close()\n", "marker.py"
    )
    path.write_text(json.dumps(record), encoding="utf-8")

    status, workdir = run_main("--replay", str(path))
    assert status == 2
    assert workdir is None  # refused before a work dir, let alone an agent
    assert not marker.exists()
    assert "logging: fixture content changed since the record" in (
        capsys.readouterr().err
    )


def _minimal_record(tmp_path, **skill_changes):
    """A hand-written record of the logging fixture's current identity."""
    fixture = run_evals.load_fixture(run_evals.FIXTURES / "logging")
    identity = run_evals.plan_fixture(fixture, "claude").identity
    identity["skill"].update(skill_changes)
    record = {
        "schema_version": 1,
        "record_type": "skilldeck-eval-run",
        "skilldeck": {"runner_sha256": None},
        "harness": {
            "name": "claude",
            "command": "claude -p {prompt}",
            "model": None,
            "version": None,
        },
        "adapter": "claude",
        "config": {"repeat": 1, "timeout_s": 60},
        "fixtures": [identity],
    }
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"canonical_sha256": "sha256:" + "0" * 64},
            "logging: skill content changed since the record",
        ),
        (
            {"rendered_sha256": "sha256:" + "0" * 64},
            "logging: installed skill file changed since the record",
        ),
        ({"version": "9.9.9"}, "logging: skill version changed since the record"),
    ],
)
def test_replay_refuses_a_changed_skill(
    no_subprocess, tmp_path, capsys, changes, message
):
    path = _minimal_record(tmp_path, **changes)
    assert run_evals.main(["--replay", str(path)]) == 2
    assert message in capsys.readouterr().err


def test_replay_dry_run_verifies_digests_and_plans(no_subprocess, tmp_path, capsys):
    path = _minimal_record(tmp_path)
    assert run_evals.main(["--replay", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "plan: 1 fixture(s) x 1 repeat(s) = 1 run(s)" in out
    assert "harness: claude (adapter claude, model harness default)" in out


def test_replay_takes_its_configuration_only_from_the_record(tmp_path, capsys):
    path = tmp_path / "record.json"
    path.write_text("{}", encoding="utf-8")
    assert run_evals.main(["--replay", str(path), "--repeat", "3", "--skill", "x"]) == 2
    assert "drop --skill, --repeat" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "cannot read the run record"),
        ("{}", "missing 'record_type'"),
        ('{"record_type": "other"}', "not a skilldeck eval run record"),
        (
            '{"record_type": "skilldeck-eval-run", "schema_version": 99}',
            "unsupported schema_version 99",
        ),
    ],
)
def test_replay_rejects_an_unreadable_record(tmp_path, capsys, text, message):
    path = tmp_path / "record.json"
    path.write_text(text, encoding="utf-8")
    assert run_evals.main(["--replay", str(path)]) == 2
    assert message in capsys.readouterr().err


def test_replay_refuses_a_fixture_that_no_longer_exists(run_main, tmp_path, capsys):
    path = _first_record(run_main, tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["fixtures"][0]["name"] = "../logging"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert run_evals.main(["--replay", str(path)]) == 2
    assert "fixture '../logging' from the record no longer exists" in (
        capsys.readouterr().err
    )
