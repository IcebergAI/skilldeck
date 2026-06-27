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
        ("0.3.0", "0.3.0"),
    ],
)
def test_normalize_tag(ref, expected):
    assert check.normalize_tag(ref) == expected


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
