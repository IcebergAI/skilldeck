"""Tests for scripts/check_release_consistency.py.

Doubles as a live guard: if the package version and the newest dated CHANGELOG
section drift apart, the suite fails here (not just in CI).
"""

import importlib.util
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
        "## [0.2.0] - 2026-01-01\n"
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
