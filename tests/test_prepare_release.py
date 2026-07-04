"""Tests for the pure file-editing parts of scripts/prepare_release.py."""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "prepare_release.py"
_spec = importlib.util.spec_from_file_location("prepare_release", _SCRIPT)
assert _spec and _spec.loader
prep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prep)

CHANGELOG = """\
# Changelog

## [Unreleased]

### Added

- something new

## [0.3.0] - 2026-06-27

### Added

- older things
"""


def test_set_pyproject_version(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.3.0"\n'
    )
    old = prep.set_pyproject_version("0.4.0", root=tmp_path)
    assert old == "0.3.0"
    assert 'version = "0.4.0"' in (tmp_path / "pyproject.toml").read_text()


def test_set_pyproject_version_rejects_same_version(tmp_path):
    (tmp_path / "pyproject.toml").write_text('version = "0.3.0"\n')
    with pytest.raises(SystemExit, match="already at"):
        prep.set_pyproject_version("0.3.0", root=tmp_path)


def test_cut_changelog_dates_the_unreleased_section(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    prep.cut_changelog("0.4.0", "2026-07-04", root=tmp_path)
    text = (tmp_path / "CHANGELOG.md").read_text()
    # fresh empty [Unreleased] above the new dated section, entries below it
    unreleased = text.index("## [Unreleased]")
    dated = text.index("## [0.4.0] - 2026-07-04")
    entry = text.index("- something new")
    older = text.index("## [0.3.0]")
    assert unreleased < dated < entry < older
    assert not text[unreleased:dated].replace("## [Unreleased]", "").strip()


def test_cut_changelog_refuses_empty_unreleased(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [0.3.0] - 2026-06-27\n\n- old\n"
    )
    with pytest.raises(SystemExit, match="nothing to release"):
        prep.cut_changelog("0.4.0", "2026-07-04", root=tmp_path)


def test_cut_changelog_refuses_duplicate_version(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    with pytest.raises(SystemExit, match="already has"):
        prep.cut_changelog("0.3.0", "2026-07-04", root=tmp_path)
