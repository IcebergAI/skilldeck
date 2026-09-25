"""Tests for scripts/build_plugin.py.

Doubles as a freshness guard: if the canonical skills (or the project version)
change without regenerating the committed Claude Code plugin tree, the suite
fails here, not just at plugin-install time. Because the plugin version is
derived from the plugin content, the same failure means a content change can't
reach ``main`` under an unchanged version (#111).
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from skilldeck.adapters.base import rendered_body
from skilldeck.provenance import (
    claude_plugin_content_digest,
    claude_plugin_version,
    parse_plugin_release,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "build_plugin.py"
_spec = importlib.util.spec_from_file_location("build_plugin", _SCRIPT)
assert _spec and _spec.loader
build_plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_plugin)


def test_committed_plugin_tree_is_current():
    problems = build_plugin.stale(build_plugin.generate())
    assert not problems, (
        "committed plugin tree is out of date; regenerate with "
        f"`python scripts/build_plugin.py`: {problems}"
    )


def test_manifests_are_valid_and_consistent():
    marketplace = json.loads(
        (_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    plugin = json.loads(
        (_ROOT / "claude-plugin" / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    assert marketplace["name"] == build_plugin.MARKETPLACE_NAME
    assert marketplace["owner"]["name"]
    (entry,) = marketplace["plugins"]
    assert entry["name"] == plugin["name"] == build_plugin.PLUGIN_NAME
    # the entry's source points at the committed plugin dir
    source = _ROOT / entry["source"]
    assert (source / ".claude-plugin" / "plugin.json").is_file()
    # plugin.json alone versions the plugin: Claude Code lets it win over the
    # marketplace entry, so a second copy could only drift
    assert "version" not in entry


def test_committed_plugin_version_follows_its_content():
    version = build_plugin.project_version()
    release = parse_plugin_release(
        json.loads((_ROOT / build_plugin.RELEASE_RECORD).read_text(encoding="utf-8"))
    )
    assert release["version"] == version
    plugin_dir = _ROOT / build_plugin.PLUGIN_DIR
    plugin = json.loads(
        (plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    files = {
        path.relative_to(plugin_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in plugin_dir.rglob("*")
        if path.is_file() and path.name not in {"plugin.json", "release.json"}
    }
    digest = claude_plugin_content_digest(plugin, files)
    assert plugin["version"] == claude_plugin_version(version, digest, release)


def test_plugin_skills_match_bundled_skills():
    from skilldeck.adapters import ADAPTERS
    from skilldeck.registry import discover_skills

    bundled = {s.name for s in discover_skills(known_agents=set(ADAPTERS))}
    committed = {
        p.parent.name for p in (_ROOT / "claude-plugin" / "skills").glob("*/SKILL.md")
    }
    assert committed == bundled


def test_plugin_provenance_matches_python_distribution():
    from skilldeck.provenance import canonical_json, content_manifest
    from skilldeck.registry import discover_skills

    plugin_provenance = json.loads(
        (_ROOT / "claude-plugin" / ".skilldeck" / "content-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    package_text = (_ROOT / "src" / "skilldeck" / "_content_manifest.json").read_text(
        encoding="utf-8"
    )
    assert package_text == canonical_json(plugin_provenance)
    assert plugin_provenance == content_manifest(build_plugin.project_version())

    by_name = {skill.name: skill for skill in discover_skills()}
    for record in plugin_provenance["skills"]:
        rendered = (
            _ROOT / "claude-plugin" / "skills" / record["name"] / "SKILL.md"
        ).read_text(encoding="utf-8")
        # the body, then the notice of what the skill declares it may do
        assert rendered.endswith(rendered_body(by_name[record["name"]]))


# --- the content-derived plugin version, on a throwaway tree ------------------

_META = """\
name: demo
description: A demo skill.
category: review
version: 0.1.0
supported-agents:
  - claude
capabilities:
  schema: 1
  files: {read: repo, write: none}
  commands: []
  network: []
  credentials: []
  tools: []
  artifacts: []
"""
_DEV_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)-dev\.sha256-[0-9a-f]{12}$")


def _tree(tmp_path: Path, version: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8"
    )
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "meta.yaml").write_text(_META, encoding="utf-8")
    (skill / "skill.md").write_text("# Demo\n\nReview carefully.\n", encoding="utf-8")
    return tmp_path


def _build(root: Path) -> str:
    """Regenerate ``root`` as a maintainer would; return the plugin version."""
    files = build_plugin.generate(root, root / "skills")
    build_plugin.write(files, root)
    assert build_plugin.stale(build_plugin.generate(root, root / "skills"), root) == []
    return build_plugin.plugin_version(files)


def _set_version(root: Path, version: str) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8"
    )


def _edit_skill(root: Path, text: str) -> None:
    (root / "skills" / "demo" / "skill.md").write_text(text, encoding="utf-8")


def _release(root: Path) -> dict:
    return json.loads((root / build_plugin.RELEASE_RECORD).read_text("utf-8"))


def test_unreleased_content_gets_a_development_version(tmp_path):
    root = _tree(tmp_path, "0.3.0")
    first = _build(root)
    # no content was ever recorded for 0.3.0, so it cannot claim that string
    assert _release(root) == {
        "content_sha256": None,
        "schema_version": 1,
        "version": "0.3.0",
    }
    match = _DEV_VERSION.fullmatch(first)
    assert match and match.groups() == ("0", "3", "1")
    assert _build(root) == first  # regenerating unchanged content is stable


def test_any_content_change_changes_the_version_and_trips_the_guard(tmp_path):
    root = _tree(tmp_path, "0.3.0")
    before = _build(root)
    _edit_skill(root, "# Demo\n\nReview very carefully.\n")
    # the freshness guard fails until the tree is regenerated...
    problems = build_plugin.stale(build_plugin.generate(root, root / "skills"), root)
    assert "outdated: claude-plugin/.claude-plugin/plugin.json" in problems
    # ...and regenerating yields a version Claude Code sees as an update
    after = _build(root)
    assert after != before
    assert _DEV_VERSION.fullmatch(after)


def test_release_prep_pins_the_exact_version_until_content_changes(tmp_path):
    root = _tree(tmp_path, "0.3.0")
    _build(root)
    _set_version(root, "0.4.0")  # what prepare_release.py does
    assert _build(root) == "0.4.0"
    assert _release(root)["version"] == "0.4.0"
    assert _release(root)["content_sha256"].startswith("sha256:")
    assert _build(root) == "0.4.0"

    _edit_skill(root, "# Demo\n\nChanged after the release.\n")
    development = _build(root)
    match = _DEV_VERSION.fullmatch(development)
    assert match and match.groups() == ("0", "4", "1")
    assert _release(root)["version"] == "0.4.0"  # the record never moves

    # reverting to the released content is the release again
    _edit_skill(root, "# Demo\n\nReview carefully.\n")
    assert _build(root) == "0.4.0"


def test_a_project_version_moving_backwards_is_refused(tmp_path):
    # e.g. pyproject.toml restored after a release prep, but not the record
    root = _tree(tmp_path, "0.4.0")
    _build(root)
    _set_version(root, "0.3.9")
    with pytest.raises(SystemExit, match="older than the plugin release record"):
        build_plugin.generate(root, root / "skills")


@pytest.mark.parametrize(
    "text",
    [
        "<<<<<<< HEAD\n",
        '{"content_sha256": null, "schema_version": 1}',
        '{"content_sha256": "sha256:00", "schema_version": 1, "version": "0.3.0"}',
        '{"content_sha256": null, "schema_version": 2, "version": "0.3.0"}',
    ],
)
def test_a_malformed_release_record_is_refused_with_a_fix(tmp_path, text):
    root = _tree(tmp_path, "0.3.0")
    record = root / build_plugin.RELEASE_RECORD
    record.parent.mkdir(parents=True)
    record.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit, match="git checkout origin/main"):
        build_plugin.generate(root, root / "skills")
