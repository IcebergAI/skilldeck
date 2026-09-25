"""The lifecycle policy (docs/lifecycle.md) and its release check.

``scripts/check_lifecycle.py`` requires CHANGELOG notes for compatibility
changes. Most tests here build a small git repository whose base commit is
``main`` and edit its working tree, as a pull request would. The walkthroughs
at the end follow docs/lifecycle.md: a skill rename, an agent removal and a
stamp-format migration, plus what installed copies look like afterwards.
"""

import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck import __version__, registry
from skilldeck.adapters import ADAPTERS, ALL_ADAPTERS
from skilldeck.adapters import base as adapter_base
from skilldeck.catalog import build_catalog
from skilldeck.cli import cli
from skilldeck.provenance import content_manifest
from skilldeck.registry import discover_skills
from test_catalog import schema_errors

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "check_lifecycle.py"
_spec = importlib.util.spec_from_file_location("check_lifecycle", _SCRIPT)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check  # dataclasses look their module up there
_spec.loader.exec_module(check)

SKILLS = check.SKILLS_PATH
TODAY = datetime.date(2026, 9, 1)


def _in_git_checkout() -> bool:
    try:
        probe = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return probe.returncode == 0


# --- the live guards ------------------------------------------------------------


def test_the_newest_release_is_a_big_enough_bump():
    assert check.main([]) == 0


@pytest.mark.skipif(not _in_git_checkout(), reason="needs a git checkout")
def test_the_working_tree_has_the_notes_it_needs_against_head(capsys):
    # exercises the git plumbing against the real repository
    assert check.main(["--base", "HEAD"]) == 0, capsys.readouterr().err


def test_the_check_reads_the_real_adapter_contracts():
    contracts = json.loads((_ROOT / check.CONTRACTS_PATH).read_text(encoding="utf-8"))
    assert set(contracts["adapters"]) == set(ALL_ADAPTERS)
    schema = (_ROOT / check.CATALOG_SCHEMA_PATH).read_text(encoding="utf-8")
    assert check._schema_version(schema) == 1


def _anchors(doc: Path) -> set[str]:
    """GitHub's heading anchors in ``doc``."""
    headings = re.findall(r"^#+ (.+)$", doc.read_text(encoding="utf-8"), re.M)
    return {
        re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
        for heading in headings
    }


def test_every_page_the_check_links_to_exists():
    source = _SCRIPT.read_text(encoding="utf-8")
    links = set(re.findall(r"(docs/[a-z-]+\.md)#([a-z0-9-]+)", source))
    links |= {
        (check.POLICY, anchor) for anchor in re.findall(r"POLICY}#([a-z0-9-]+)", source)
    }
    assert len(links) >= 8
    for page, anchor in sorted(links):
        assert anchor in _anchors(_ROOT / page), f"{page}#{anchor}"


# --- parsing the CHANGELOG -------------------------------------------------------

CHANGELOG = """\
# Changelog

Intro text with `old-review` in it, which is not an entry.

## [Unreleased]

### Removed

- `old-review`: use `new-review`, which also covers X. Delete leftovers
  with the paths `skilldeck status` prints.
  - a nested bullet naming `nested-name`
- `other` goes too.

### deprecated

- `legacy-review`

## [0.3.0] - 2026-06-27

### Added

- `just-released`

## [0.10.0] - 2026-07-01

### Changed

- `newest-by-number`

## [0.1.0]

### Added

- `undated`
"""


def test_parse_changelog_splits_sections_groups_and_entries():
    sections = check.parse_changelog(CHANGELOG.replace("\n", "\r\n"))
    assert [(s.version, s.date) for s in sections] == [
        (None, None),
        ("0.3.0", datetime.date(2026, 6, 27)),
        ("0.10.0", datetime.date(2026, 7, 1)),
        ("0.1.0", None),
    ]
    unreleased = sections[0]
    assert unreleased.entries("Removed") == [
        "`old-review`: use `new-review`, which also covers X. Delete leftovers\n"
        "  with the paths `skilldeck status` prints.\n"
        "  - a nested bullet naming `nested-name`",
        "`other` goes too.",
    ]
    assert unreleased.entries("Deprecated") == ["`legacy-review`"]  # title-cased
    # [Unreleased] and the newest dated section by number, not file order
    assert [s.version for s in check.recent_sections(sections)] == [None, "0.10.0"]


def test_names_needs_every_term_in_backticks():
    entry = "`old-review` no longer supports `codex`; old-review lives on"
    assert check.names(entry, "old-review", "codex")
    assert not check.names(entry, "old-review", "claude")
    assert not check.names("old-review was removed", "old-review")
    assert not check.names("`old-review-2` was removed", "old-review")


def test_mentions_version_matches_whole_versions_only():
    assert check.mentions_version("now 2.0.0.", "2.0.0")
    assert not check.mentions_version("now 12.0.0", "2.0.0")
    assert not check.mentions_version("now 2.0.01", "2.0.0")


# --- the version bump the newest release needs -------------------------------


def _releases(newest: str, previous: str, body: str) -> str:
    return (
        f"## [Unreleased]\n\n## [{newest}] - 2026-08-01\n\n{body}\n"
        f"## [{previous}] - 2026-07-01\n\n### Added\n\n- old\n"
    )


@pytest.mark.parametrize(
    "newest, previous, body, needed",
    [
        ("0.4.1", "0.4.0", "### Fixed\n\n- a bug\n", None),
        ("0.4.1", "0.4.0", "### Security\n\n- a fix\n", None),
        ("0.4.1", "0.4.0", "### Removed\n\n- `x`\n", "a minor release (0.5.0)"),
        ("0.4.1", "0.4.0", "### Deprecated\n\n- `x`\n", "a minor release (0.5.0)"),
        ("0.4.1", "0.4.0", "### Changed\n\n- **Breaking:** y\n", "(0.5.0)"),
        ("0.5.0", "0.4.0", "### Removed\n\n- `x`\n", None),  # pre-1.0: minor
        ("1.0.0", "0.4.0", "### Removed\n\n- `x`\n", None),
        ("1.2.1", "1.2.0", "### Deprecated\n\n- `x`\n", "a minor release (1.3.0)"),
        ("1.3.0", "1.2.0", "### Deprecated\n\n- `x`\n", None),
        ("1.3.0", "1.2.0", "### Removed\n\n- `x`\n", "a major release (2.0.0)"),
        ("1.2.1", "1.2.0", "### Removed\n\n- `x`\n", "a major release (2.0.0)"),
        ("2.0.0", "1.2.0", "### Removed\n\n- `x`\n", None),
    ],
)
def test_release_bump_rule(newest, previous, body, needed):
    errors = check.release_bump_errors(
        check.parse_changelog(_releases(newest, previous, body))
    )
    if needed is None:
        assert errors == []
    else:
        assert len(errors) == 1
        assert needed in errors[0]
        assert "docs/lifecycle.md#the-package" in errors[0]


def test_release_bump_rule_needs_two_dated_releases():
    text = "## [Unreleased]\n\n## [0.4.1] - 2026-08-01\n\n### Removed\n\n- `x`\n"
    assert check.release_bump_errors(check.parse_changelog(text)) == []


# --- a synthetic repository -----------------------------------------------------


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # LF on every platform


def write_skill(repo, name, version="1.2.0", agents=("claude", "codex"), **deprec):
    """Write skill ``name``; ``deprec`` (since, reason, replacement) deprecates."""
    lines = [
        f"name: {name}",
        f"description: The {name} skill.",
        "category: testing",
        f"version: {version}",
        "supported-agents:",
        *(f"  - {agent}" for agent in agents),
    ]
    if deprec:
        lines += ["deprecated:", *(f"  {k}: {v}" for k, v in deprec.items())]
    _write(repo / SKILLS / name / "meta.yaml", "\n".join(lines) + "\n")
    _write(repo / SKILLS / name / "skill.md", f"# {name}\n")


def write_changelog(repo, unreleased="", released=""):
    _write(
        repo / "CHANGELOG.md",
        "# Changelog\n\n## [Unreleased]\n\n"
        f"{unreleased}\n{released}"
        "## [0.1.0] - 2026-01-01\n\n### Added\n\n- The first release.\n",
    )


def write_schema(repo, version=1):
    schema = {"properties": {"schema_version": {"const": version}}}
    _write(repo / check.CATALOG_SCHEMA_PATH, json.dumps(schema))


def write_version(repo, version):
    _write(repo / "pyproject.toml", f'[project]\nname = "x"\nversion = "{version}"\n')


def commit(repo, message="change"):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """``main``: two skills and every current adapter, released as nothing yet."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    write_skill(root, "old-review")
    write_skill(root, "other-review", agents=("claude", "codex", "copilot"))
    contracts = {"adapters": {name: {} for name in sorted(ALL_ADAPTERS)}}
    _write(root / check.CONTRACTS_PATH, json.dumps(contracts))
    write_schema(root)
    write_changelog(root)
    write_version(root, "0.1.0")
    commit(root, "base")
    monkeypatch.setattr(check, "ROOT", root)
    return root


def errors(today=TODAY):
    return check.lifecycle_errors("main", today)


def test_no_compatibility_change_needs_no_note(repo):
    write_skill(repo, "old-review", version="1.2.1")  # a patch: no note
    write_skill(repo, "brand-new")  # additions need no lifecycle note
    assert errors() == []


def test_the_base_ref_must_exist(repo):
    assert check.lifecycle_errors("origin/nope") == [
        "base ref 'origin/nope' not found (fetch it first)"
    ]


def test_base_needs_a_git_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert check.lifecycle_errors("main") == ["--base main needs a git checkout"]


# --- removing a skill -----------------------------------------------------------


def test_removing_a_skill_needs_a_removed_entry_and_a_deprecation(repo):
    shutil.rmtree(repo / SKILLS / "old-review")
    found = errors()
    assert len(found) == 2
    assert found[0].startswith(
        "skill `old-review` was removed: add a `### Removed` entry naming "
        "`old-review` (in backticks) under `## [Unreleased]` in CHANGELOG.md"
    )
    assert "docs/lifecycle.md#removing-a-skill" in found[0]
    assert "without being deprecated first" in found[1]
    assert "`### Security` entry naming `old-review`" in found[1]

    write_changelog(repo, "### Removed\n\n- `old-review`: use `other-review`.\n")
    assert [e for e in errors() if "deprecated first" not in e] == []


def test_an_entry_in_the_wrong_group_or_section_does_not_count(repo):
    shutil.rmtree(repo / SKILLS / "old-review")
    write_changelog(
        repo,
        "### Changed\n\n- `old-review` is gone.\n",
        "## [0.2.0] - 2026-02-01\n\n### Added\n\n- `old-review`\n\n"
        "## [0.1.1] - 2026-01-15\n\n### Removed\n\n- `old-review`\n\n",
    )
    assert any("add a `### Removed` entry" in e for e in errors())


def test_an_urgent_security_removal_skips_the_deprecation(repo):
    shutil.rmtree(repo / SKILLS / "old-review")
    write_changelog(
        repo,
        "### Security\n\n- `old-review` told agents to disable TLS checks.\n\n"
        "### Removed\n\n- `old-review`, for the reason under Security.\n",
    )
    assert errors() == []


def test_removing_a_deprecated_skill_no_release_contains(repo):
    # never in a tagged release: nobody holds a release to give notice to
    write_skill(repo, "old-review", reason="Obsolete.", since="1.2.0")
    write_changelog(repo, "### Deprecated\n\n- `old-review`\n")
    commit(repo)
    shutil.rmtree(repo / SKILLS / "old-review")
    write_changelog(repo, "### Removed\n\n- `old-review`\n")
    assert errors() == []


@pytest.fixture
def released_deprecation(repo):
    """``old-review`` shipped deprecated in the tagged release 0.2.0."""
    write_skill(repo, "old-review", reason="Obsolete.", since="1.2.0")
    deprecated = (
        "## [0.2.0] - 2026-06-01\n\n### Deprecated\n\n"
        "- `old-review`: obsolete; removal no earlier than 90 days from now.\n\n"
    )
    write_changelog(repo, released=deprecated)
    commit(repo, "release 0.2.0")
    _git(repo, "tag", "v0.2.0")
    shutil.rmtree(repo / SKILLS / "old-review")
    write_changelog(repo, "### Removed\n\n- `old-review`\n", deprecated)
    return repo


def test_removal_waits_for_the_notice_period(released_deprecation):
    assert errors(datetime.date(2026, 8, 29)) == [
        "skill `old-review` was removed too early: its deprecation was published "
        "in 0.2.0 on 2026-06-01, so it can be removed from 2026-08-30 (90 days' "
        "notice; docs/lifecycle.md#removing-a-skill)"
    ]
    assert errors(datetime.date(2026, 8, 30)) == []


def test_from_1_0_the_notice_period_is_180_days(released_deprecation):
    write_version(released_deprecation, "1.0.0")
    (found,) = errors(datetime.date(2026, 11, 27))
    assert "can be removed from 2026-11-28 (180 days' notice" in found
    assert errors(datetime.date(2026, 11, 28)) == []


def test_the_notice_counts_only_from_a_published_release(released_deprecation):
    # a dated section without its tag is prepared, not published
    _git(released_deprecation, "tag", "-d", "v0.2.0")
    _git(released_deprecation, "tag", "v0.1.0", "HEAD")  # the skill was released
    (found,) = errors(datetime.date(2027, 1, 1))
    assert "no published release announces its deprecation" in found


# --- deprecating, dropping an agent, a major version, the catalog schema ------


def test_a_new_deprecation_needs_a_deprecated_entry(repo):
    write_skill(repo, "old-review", "1.3.0", since="1.3.0", reason="Obsolete.")
    assert errors() == [
        "skill `old-review` is newly deprecated: add a `### Deprecated` entry "
        "naming `old-review` (in backticks) under `## [Unreleased]` in "
        "CHANGELOG.md, naming its replacement or the reason "
        "(docs/lifecycle.md#deprecating-a-skill)"
    ]
    write_changelog(repo, "### Deprecated\n\n- `old-review`: obsolete.\n")
    assert errors() == []


def test_the_newest_dated_section_counts_after_a_release_cut(repo):
    write_skill(repo, "old-review", "1.3.0", since="1.3.0", reason="Obsolete.")
    write_changelog(
        repo, released="## [0.2.0] - 2026-09-01\n\n### Deprecated\n\n- `old-review`\n"
    )
    assert errors() == []


def test_a_major_skill_version_needs_a_changed_entry(repo):
    write_skill(repo, "old-review", version="2.0.0")
    (found,) = errors()
    assert found.startswith(
        "skill `old-review` went from 1.2.0 to 2.0.0, a major (breaking) change: "
        "add a `### Changed` entry naming `old-review` and 2.0.0"
    )
    write_changelog(repo, "### Changed\n\n- `old-review` now reports X.\n")
    assert errors() == [found]  # the entry must give the new version
    write_changelog(repo, "### Changed\n\n- `old-review` 2.0.0 drops area Y.\n")
    assert errors() == []


def test_a_catalog_schema_version_change_needs_a_breaking_entry(repo):
    write_schema(repo, 2)
    (found,) = errors()
    assert "catalog schema_version changed from 1 to 2" in found
    write_changelog(
        repo, "### Changed\n\n- **Breaking:** the catalog `schema_version` is 2.\n"
    )
    assert errors() == []


# --- walkthrough (a): renaming a skill ------------------------------------------


def _catalog(repo):
    skills = discover_skills(repo / SKILLS, known_agents=ADAPTERS)
    catalog = build_catalog(skills, content_manifest(__version__, skills))
    assert schema_errors(catalog, exact=True) == []
    return {skill["name"]: skill["deprecated"] for skill in catalog["skills"]}


def test_walkthrough_renaming_a_skill(repo):
    """old-review becomes new-review: add, deprecate, wait, remove."""
    _git(repo, "tag", "v0.1.0")  # old-review is in a release

    # 1. the rename PR: the new name, and the old one deprecated in its favour
    write_skill(repo, "new-review", version="1.3.0")
    write_skill(
        repo,
        "old-review",
        version="1.3.0",
        since="1.3.0",
        replacement="new-review",
        reason="Renamed to new-review.",
    )
    assert _catalog(repo) == {
        "new-review": None,
        "old-review": {
            "since": "1.3.0",
            "replacement": "new-review",
            "reason": "Renamed to new-review.",
        },
        "other-review": None,
    }
    assert [e.split(":")[0] for e in errors()] == [
        "skill `old-review` is newly deprecated"
    ]
    notes = (
        "### Added\n\n- `new-review` (1.3.0), the new name of `old-review`.\n\n"
        "### Deprecated\n\n- `old-review`: renamed to `new-review`; install that "
        "instead. It will be removed no earlier than 90 days after this release.\n"
    )
    write_changelog(repo, notes)
    assert errors() == []

    # 2. the release that publishes the deprecation
    released = notes.replace("### Added", "## [0.2.0] - 2026-06-01\n\n### Added")
    write_changelog(repo, released=released + "\n")
    commit(repo, "release 0.2.0")
    _git(repo, "tag", "v0.2.0")

    # 3. at least 90 days later, the removal PR
    shutil.rmtree(repo / SKILLS / "old-review")
    assert [e.split(":")[0] for e in errors(datetime.date(2026, 9, 1))] == [
        "skill `old-review` was removed"
    ]
    write_changelog(
        repo,
        "### Removed\n\n- `old-review`, deprecated in 0.2.0: use `new-review`.\n",
        released + "\n",
    )
    assert errors(datetime.date(2026, 8, 29)) != []  # too early
    assert errors(datetime.date(2026, 9, 1)) == []
    # a removed skill is simply absent: the CHANGELOG records it
    assert _catalog(repo) == {"new-review": None, "other-review": None}


def test_the_catalog_represents_every_lifecycle_state(repo):
    write_skill(repo, "new-review")
    write_skill(repo, "old-review", since="1.2.0", replacement="new-review", reason="R")
    write_skill(repo, "other-review", since="1.2.0", reason="No longer maintained.")
    assert _catalog(repo) == {
        "new-review": None,  # active
        "old-review": {"since": "1.2.0", "replacement": "new-review", "reason": "R"},
        "other-review": {  # deprecated with a rationale only
            "since": "1.2.0",
            "replacement": None,
            "reason": "No longer maintained.",
        },
    }


# --- walkthrough (b): removing an agent -----------------------------------------


def test_walkthrough_dropping_an_agent_from_a_skill(repo):
    write_skill(repo, "other-review", agents=("claude", "codex"))
    (found,) = errors()
    assert found.startswith(
        "skill `other-review` no longer supports `copilot`: add one `### Removed` "
        "entry naming both `other-review` and `copilot` (in backticks)"
    )
    assert "`skilldeck uninstall other-review --agent copilot`" in found
    # naming them in two different entries is not enough
    write_changelog(repo, "### Removed\n\n- `other-review`\n- `copilot` things\n")
    assert errors() == [found]
    write_changelog(
        repo,
        "### Removed\n\n- `other-review` no longer supports `copilot`: remove "
        "installed copies with `skilldeck uninstall other-review --agent copilot`.\n",
    )
    assert errors() == []


@pytest.mark.parametrize("adapter", ["copilot", "kiro-steering"])
def test_walkthrough_removing_an_adapter(repo, monkeypatch, adapter):
    remaining = {k: v for k, v in ALL_ADAPTERS.items() if k != adapter}
    monkeypatch.setattr(check, "ALL_ADAPTERS", remaining)
    if adapter in ADAPTERS:
        # skills can no longer list a removed native agent; that is covered by
        # the adapter's note, not one per skill
        write_skill(repo, "other-review", agents=("claude", "codex"))
    assert errors() == [
        f"adapter `{adapter}` was removed: add a `### Removed` entry naming "
        f"`{adapter}` (in backticks) under `## [Unreleased]` in CHANGELOG.md, "
        "listing the paths it installed to so users can delete what is left "
        "(docs/lifecycle.md#removing-an-agent-or-format)"
    ]
    write_changelog(repo, f"### Removed\n\n- The `{adapter}` adapter.\n")
    assert errors() == []


def test_main_reports_what_is_missing_and_links_the_policy(repo, capsys):
    shutil.rmtree(repo / SKILLS / "old-review")
    assert check.main(["--base", "main"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: skill `old-review` was removed")
    assert "See docs/lifecycle.md" in err


# --- what happens to installed copies (docs/lifecycle.md says so) -------------


def _runner():
    # Click < 8.2 mixes stderr into stdout unless told not to; 8.2 dropped the
    # flag and always captures the streams separately
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _run(*args):
    result = _runner().invoke(cli, list(args))
    assert result.exit_code == 0, (result.stdout, result.stderr)
    return result


@pytest.fixture
def installed(repo, tmp_path, monkeypatch):
    """Both skills installed for claude and codex in a project."""
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", repo / SKILLS)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    _run("install", "--all", "--agent", "claude", "--agent", "codex")
    return project


def test_installed_copies_of_a_removed_skill(repo, installed):
    shutil.rmtree(repo / SKILLS / "old-review")
    left = Path(".claude/skills/old-review/SKILL.md")
    status = _run("status", "--agent", "claude").stdout
    assert f"orphan: {Path.cwd().resolve() / left} (old-review 1.2.0)" in status
    assert "nothing to update" in _run("update", "--agent", "claude").stdout
    result = _run("uninstall", "--all", "--agent", "claude")
    assert "old-review" not in result.stdout
    assert left.is_file()  # skilldeck leaves it: delete it by hand
    with pytest.raises(registry.SkillError, match="unknown skill: old-review"):
        _runner().invoke(
            cli,
            ["uninstall", "old-review", "--agent", "claude"],
            catch_exceptions=False,
        )


def test_installed_copies_for_an_agent_a_skill_dropped(repo, installed):
    write_skill(repo, "other-review", version="1.3.0", agents=("claude",))
    kept = Path(".agents/skills/other-review/SKILL.md")
    # status and update for that agent no longer look at it...
    assert "other-review" not in _run("status", "--agent", "codex").stdout
    assert "other-review" not in _run("update", "--agent", "codex").stdout
    assert "1.2.0" in kept.read_text(encoding="utf-8")
    # ...but uninstall still removes it
    removed = _run("uninstall", "other-review", "--agent", "codex").stdout
    assert f"removed other-review <- {Path.cwd().resolve() / kept}" in removed
    assert not kept.exists()


# --- walkthrough (c): a stamp-format migration -----------------------------------

real_stamp = adapter_base.stamp
real_parse = adapter_base.parse

# A hypothetical second stamp format, with the explicit marker that
# docs/lifecycle.md#install-stamps asks the next format to carry.
_V2_RE = re.compile(
    r"<!-- skilldeck stamp=2 name=(?P<name>\S+) version=(?P<version>\S+) "
    r"hash=(?P<hash>[0-9a-f]{64}) -->\n?"
)


def _stamp_v2(content, name, version):
    v1 = real_stamp(content, name, version)
    return v1.replace("<!-- skilldeck name=", "<!-- skilldeck stamp=2 name=")


def _parse_v1_or_v2(text):
    """The migration rule: read the new format, and still read the old one."""
    matches = list(_V2_RE.finditer(text))
    if not matches:
        return real_parse(text)
    last = matches[-1]
    v1_line = last.group(0).replace(" stamp=2 ", " ")
    return real_parse(text[: last.start()] + v1_line + text[last.end() :])


def test_walkthrough_stamp_format_migration(repo, installed, monkeypatch):
    edited = Path(".agents/skills/old-review/SKILL.md")
    edited.write_bytes(edited.read_bytes().replace(b"# old-review", b"# mine"))
    monkeypatch.setattr(adapter_base, "stamp", _stamp_v2)
    monkeypatch.setattr(adapter_base, "parse", _parse_v1_or_v2)

    # unedited v1 installs are stale, since installing now writes v2...
    status = _run("status", "--agent", "all").stdout
    assert "old-review    1.2.0 stale (bundled: 1.2.0)" in status
    assert "old-review    1.2.0 modified locally" in status  # codex: edited
    # ...so `update` rewrites them without --force, and skips the edited one
    result = _run("update", "--agent", "claude", "--agent", "codex")
    assert "updated old-review (1.2.0 -> 1.2.0)" in result.stdout
    assert "skip old-review: locally modified (use --force)" in result.stderr
    migrated = Path(".claude/skills/old-review/SKILL.md").read_text(encoding="utf-8")
    assert "<!-- skilldeck stamp=2 name=old-review version=1.2.0 hash=" in migrated
    assert "# mine" in edited.read_text(encoding="utf-8")
    assert "up to date" in _run("status", "--agent", "claude").stdout
    # an older skilldeck that knows only v1 sees the new file as unmanaged
    assert real_parse(migrated) is None
