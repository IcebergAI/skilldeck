"""Tests for scripts/prepare_release.py."""

import importlib.util
import json
import subprocess
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

PYPROJECT = """\
[project]
name = "demo"
version = "0.3.0"

[tool.decoy]
version = "0.3.0"
"""


def test_bump_pyproject_rewrites_only_the_project_version():
    text, old = prep.bump_pyproject(PYPROJECT, "0.4.0")
    assert old == "0.3.0"
    assert text == PYPROJECT.replace('version = "0.3.0"', 'version = "0.4.0"', 1)
    assert text.endswith('[tool.decoy]\nversion = "0.3.0"\n')


def test_bump_pyproject_rejects_same_version():
    with pytest.raises(SystemExit, match="already at"):
        prep.bump_pyproject(PYPROJECT, "0.3.0")


def test_bump_pyproject_rejects_older_version():
    with pytest.raises(SystemExit, match="older than"):
        prep.bump_pyproject(PYPROJECT, "0.2.9")


def test_cut_changelog_dates_the_unreleased_section():
    text = prep.cut_changelog(CHANGELOG, "0.4.0", "2026-07-04")
    # fresh empty [Unreleased] above the new dated section, entries below it
    unreleased = text.index("## [Unreleased]")
    dated = text.index("## [0.4.0] - 2026-07-04")
    entry = text.index("- something new")
    older = text.index("## [0.3.0]")
    assert unreleased < dated < entry < older
    assert not text[unreleased:dated].replace("## [Unreleased]", "").strip()


def test_cut_changelog_refuses_empty_unreleased():
    empty = "# Changelog\n\n## [Unreleased]\n\n## [0.3.0] - 2026-06-27\n\n- old\n"
    with pytest.raises(SystemExit, match="nothing to release"):
        prep.cut_changelog(empty, "0.4.0", "2026-07-04")


def test_cut_changelog_refuses_unreleased_with_only_headings():
    headings = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n### Fixed\n\n"
        "## [0.3.0] - 2026-06-27\n\n- old\n"
    )
    with pytest.raises(SystemExit, match="no entries"):
        prep.cut_changelog(headings, "0.4.0", "2026-07-04")


def test_cut_changelog_refuses_a_version_below_the_newest_release():
    # a stray newer section would make the post-write consistency guard fail
    ahead = CHANGELOG + "\n## [0.5.0] - 2026-06-28\n\n- stray\n"
    with pytest.raises(SystemExit, match="older than CHANGELOG.md's newest release"):
        prep.cut_changelog(ahead, "0.4.0", "2026-07-04")


def test_cut_changelog_refuses_duplicate_version():
    with pytest.raises(SystemExit, match="already has"):
        prep.cut_changelog(CHANGELOG, "0.3.0", "2026-07-04")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A fake repo root; main() runs against it with uv and the plugin stubbed."""
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "uv.lock").write_text("old lock\n", encoding="utf-8")
    monkeypatch.setattr(prep, "ROOT", tmp_path)
    monkeypatch.setattr(prep.build_plugin, "generate", lambda: _plugin("0.4.0"))
    monkeypatch.setattr(prep.build_plugin, "write", lambda files: None)
    return tmp_path


def _plugin(version):
    """A stand-in :func:`build_plugin.generate` result holding just plugin.json."""
    path = prep.build_plugin.PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    return {path: json.dumps({"version": version})}


def _snapshot(root):
    return {
        name: (root / name).read_text(encoding="utf-8")
        for name in ("pyproject.toml", "CHANGELOG.md", "uv.lock")
    }


def _fake_run(uv_lock_returncode, root=None):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["uv", "lock"]:
            if root is not None:  # a real `uv lock` rewrites the lockfile
                (root / "uv.lock").write_text("new lock\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, uv_lock_returncode)
        return subprocess.CompletedProcess(cmd, 0)

    return run, calls


@pytest.mark.parametrize(
    "version, message",
    [
        ("0.3.0", "already at"),  # pyproject rejects it after the CHANGELOG is ok
        ("0.4", "not a MAJOR.MINOR.PATCH"),
        ("0.04.0", "no leading zeros"),  # PEP 440 would publish it as 0.4.0
        ("0.2.0", "older than"),
    ],
)
def test_main_validates_everything_before_writing(tree, monkeypatch, version, message):
    run, calls = _fake_run(0)
    monkeypatch.setattr(prep.subprocess, "run", run)
    before = _snapshot(tree)
    with pytest.raises(SystemExit, match=message):
        prep.main([version])
    assert _snapshot(tree) == before
    assert calls == []


def test_main_refuses_existing_changelog_section_without_bumping(tree, monkeypatch):
    run, _ = _fake_run(0)
    monkeypatch.setattr(prep.subprocess, "run", run)
    (tree / "CHANGELOG.md").write_text(
        CHANGELOG + "\n## [0.4.0] - 2026-01-01\n\n- misplaced\n", encoding="utf-8"
    )
    before = _snapshot(tree)
    with pytest.raises(SystemExit, match="already has a 0.4.0 section"):
        prep.main(["0.4.0"])
    assert _snapshot(tree) == before


def test_main_rolls_back_and_fails_when_uv_lock_fails(tree, monkeypatch, capsys):
    run, calls = _fake_run(1)
    monkeypatch.setattr(prep.subprocess, "run", run)
    before = _snapshot(tree)
    assert prep.main(["0.4.0"]) == 1
    assert _snapshot(tree) == before
    assert calls == [["uv", "lock"]]
    assert "`uv lock` failed" in capsys.readouterr().err


def test_main_rolls_back_when_uv_is_missing(tree, monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError("uv")

    monkeypatch.setattr(prep.subprocess, "run", missing)
    before = _snapshot(tree)
    assert prep.main(["0.4.0"]) == 1
    assert _snapshot(tree) == before


def test_main_rolls_back_everything_when_plugin_generation_fails(tree, monkeypatch):
    run, calls = _fake_run(0, root=tree)
    monkeypatch.setattr(prep.subprocess, "run", run)

    def broken():
        raise SystemExit("error: skill 'demo': invalid meta.yaml")

    monkeypatch.setattr(prep.build_plugin, "generate", broken)
    before = _snapshot(tree)
    with pytest.raises(SystemExit, match="invalid meta.yaml"):
        prep.main(["0.4.0"])
    assert calls == [["uv", "lock"]]
    assert _snapshot(tree) == before  # uv.lock included


def test_main_prepares_the_release(tree, monkeypatch, capsys):
    run, calls = _fake_run(0)
    monkeypatch.setattr(prep.subprocess, "run", run)
    assert prep.main(["v0.4.0"]) == 0
    after = _snapshot(tree)
    assert 'version = "0.4.0"' in after["pyproject.toml"]
    assert "## [0.4.0] - " in after["CHANGELOG.md"]
    assert calls[0] == ["uv", "lock"]
    out = capsys.readouterr().out
    # the hint must keep the dev tools installed (bare `uv run` drops extras)
    assert "uv run --extra dev pytest" in out
    assert "uv run ruff" not in out


def test_main_rolls_back_when_the_plugin_would_not_carry_the_release_version(
    tree, monkeypatch, capsys
):
    # a plugin release record the bump did not supersede keeps a dev version
    run, _ = _fake_run(0, root=tree)
    monkeypatch.setattr(prep.subprocess, "run", run)
    monkeypatch.setattr(
        prep.build_plugin, "generate", lambda: _plugin("0.4.1-dev.sha256-0123456789ab")
    )
    written = []
    monkeypatch.setattr(prep.build_plugin, "write", written.append)
    before = _snapshot(tree)
    assert prep.main(["0.4.0"]) == 1
    assert _snapshot(tree) == before
    assert written == []
    assert "not 0.4.0" in capsys.readouterr().err
