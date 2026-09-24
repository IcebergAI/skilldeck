"""Tests for scripts/check_release_consistency.py.

Doubles as a live guard: if the package version and the newest dated CHANGELOG
section drift apart, the suite fails here (not just in CI).
"""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "check_release_consistency.py"
_spec = importlib.util.spec_from_file_location("check_release_consistency", _SCRIPT)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def test_version_matches_changelog():
    assert check.project_version() == check.latest_changelog_version()


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("v0.3.0", "0.3.0"),
        ("refs/tags/v0.3.0", "0.3.0"),
        ("v0.10.12", "0.10.12"),
        ("v1.0.10", "1.0.10"),
    ],
)
def test_normalize_tag(ref, expected):
    assert check.normalize_tag(ref) == expected


@pytest.mark.parametrize(
    "ref",
    [
        "0.3.0",  # no v prefix
        "refs/tags/x/v0.3.0",  # nested tag: its last segment must not win
        "refs/heads/v0.3.0",  # a branch, not a tag
        "tags/v0.3.0",
        "v0.3",
        "v0.3.0rc1",
        "v0.3.0\n",
        "refs/tags/v0.3.0 ",
        "v\u0663.0.0",  # non-ASCII digits
        "v0.04.0",  # PEP 440 would publish it as 0.4.0
        "v01.0.0",
    ],
)
def test_normalize_tag_rejects_anything_but_an_exact_tag(ref):
    with pytest.raises(ValueError, match="not of the form vX.Y.Z"):
        check.normalize_tag(ref)


def test_latest_changelog_version_picks_highest_not_first(monkeypatch, tmp_path):
    # Robust to a section added in the wrong place, and compares numerically
    # (string order would rank 0.3.0 above 0.10.0).
    (tmp_path / "CHANGELOG.md").write_text(
        "## [0.3.0] - 2026-01-02\n\n"
        "## [0.10.0] - 2026-01-03\n\n"
        "## [0.2.0] - 2026-01-01\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "ROOT", tmp_path)
    assert check.latest_changelog_version() == "0.10.0"


def test_main_passes_with_no_tag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["check_release_consistency.py"])
    assert check.main() == 0
    assert "ok:" in capsys.readouterr().out


def test_main_passes_with_matching_tag(monkeypatch):
    version = check.project_version()
    monkeypatch.setattr(
        "sys.argv", ["check_release_consistency.py", "--tag", f"v{version}"]
    )
    assert check.main() == 0


def test_main_fails_with_mismatched_tag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["check_release_consistency.py", "--tag", "v9.9.9"])
    assert check.main() == 1
    assert "error:" in capsys.readouterr().err


def test_main_rejects_a_nested_tag_even_if_it_ends_in_the_version(monkeypatch, capsys):
    version = check.project_version()
    monkeypatch.setattr(
        "sys.argv",
        ["check_release_consistency.py", "--tag", f"refs/tags/x/v{version}"],
    )
    assert check.main() == 1
    assert "not of the form vX.Y.Z" in capsys.readouterr().err


def test_project_version_ignores_other_tables(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.x]\nversion = "9.9.9"\n\n[project]\nname = "x"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "ROOT", tmp_path)
    assert check.project_version() == "1.2.3"


# --- the plugin release record guard -------------------------------------


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


def _write_state(repo, version, record_version, digest, plugin_version):
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8"
    )
    record = repo / check.RELEASE_RECORD
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        json.dumps(
            {"content_sha256": digest, "schema_version": 1, "version": record_version}
        ),
        encoding="utf-8",
    )
    plugin = repo / check.PLUGIN_JSON
    plugin.parent.mkdir(parents=True, exist_ok=True)
    plugin.write_text(json.dumps({"version": plugin_version}), encoding="utf-8")


@pytest.fixture
def released_repo(tmp_path, monkeypatch):
    """A repo whose 0.3.1 release (content ``aaa``) is tagged v0.3.1 on main."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _write_state(tmp_path, "0.3.1", "0.3.1", "a" * 64, "0.3.1")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "release")
    _git(tmp_path, "tag", "v0.3.1")
    monkeypatch.setattr(check, "ROOT", tmp_path)
    return tmp_path


def test_record_guard_accepts_the_tagged_record_and_dev_content(released_repo):
    assert check.plugin_record_errors("0.3.1") == []
    # content changed after the release: a development version, record kept
    _write_state(released_repo, "0.3.1", "0.3.1", "a" * 64, "0.3.2-dev.sha256-x")
    assert check.plugin_record_errors("0.3.1", "main") == []


def test_record_guard_rejects_rewriting_a_tagged_record(released_repo):
    # the reverted-record attack: new content re-recorded as released 0.3.1
    _write_state(released_repo, "0.3.1", "0.3.1", "b" * 64, "0.3.1")
    errors = check.plugin_record_errors("0.3.1")
    assert len(errors) == 1
    assert "differs from the copy tagged refs/tags/v0.3.1" in errors[0]


def test_record_guard_rejects_a_record_change_without_a_version_bump(
    released_repo,
):
    _git(released_repo, "tag", "-d", "v0.3.1")  # prepared, not yet tagged
    _write_state(released_repo, "0.3.1", "0.3.1", "b" * 64, "0.3.1")
    assert check.plugin_record_errors("0.3.1") == []  # nothing tagged to compare
    errors = check.plugin_record_errors("0.3.1", "main")
    assert len(errors) == 1
    assert "changed without a project version bump" in errors[0]


def test_record_guard_requires_a_release_pr_to_ship_the_release_plugin(
    released_repo,
):
    _write_state(released_repo, "0.4.0", "0.4.0", "c" * 64, "0.4.0")
    assert check.plugin_record_errors("0.4.0", "main") == []
    # main merged into the release PR after prepare_release.py: content drifted
    _write_state(released_repo, "0.4.0", "0.4.0", "c" * 64, "0.4.1-dev.sha256-d")
    errors = check.plugin_record_errors("0.4.0", "main")
    assert len(errors) == 1
    assert "development snapshot '0.4.1-dev.sha256-d'" in errors[0]


def test_record_guard_reports_a_missing_base_ref(released_repo):
    errors = check.plugin_record_errors("0.3.1", "origin/nope")
    assert errors == ["base ref 'origin/nope' not found (fetch it first)"]


def test_record_guard_skips_git_checks_outside_a_checkout(tmp_path, monkeypatch):
    _write_state(tmp_path, "0.3.1", "0.3.1", "a" * 64, "0.3.1")
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert check.plugin_record_errors("0.3.1") == []
    assert check.plugin_record_errors("0.3.1", "main") == [
        "--base main needs a git checkout"
    ]


def test_main_with_base_fails_on_a_rewritten_record(released_repo, capsys, monkeypatch):
    (released_repo / "CHANGELOG.md").write_text(
        "## [0.3.1] - 2026-01-01\n", encoding="utf-8"
    )
    _write_state(released_repo, "0.3.1", "0.3.1", "b" * 64, "0.3.1")
    monkeypatch.setattr("sys.argv", ["check_release_consistency.py", "--base", "main"])
    assert check.main() == 1
    err = capsys.readouterr().err
    assert "differs from the copy tagged" in err
    assert "changed without a project version bump" in err
