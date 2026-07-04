"""Tests for scripts/build_plugin.py.

Doubles as a freshness guard: if the canonical skills (or the project version)
change without regenerating the committed Claude Code plugin tree, the suite
fails here, not just at plugin-install time.
"""

import importlib.util
import json
from pathlib import Path

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
        (_ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )
    plugin = json.loads(
        (_ROOT / "claude-plugin" / ".claude-plugin" / "plugin.json").read_text()
    )
    assert marketplace["name"] == build_plugin.MARKETPLACE_NAME
    assert marketplace["owner"]["name"]
    (entry,) = marketplace["plugins"]
    assert entry["name"] == plugin["name"] == build_plugin.PLUGIN_NAME
    # the entry's source points at the committed plugin dir
    source = _ROOT / entry["source"]
    assert (source / ".claude-plugin" / "plugin.json").is_file()
    # plugin version tracks the installer version
    assert plugin["version"] == build_plugin.project_version()


def test_plugin_skills_match_bundled_skills():
    from skilldeck.adapters import ADAPTERS
    from skilldeck.registry import discover_skills

    bundled = {s.name for s in discover_skills(known_agents=set(ADAPTERS))}
    committed = {
        p.parent.name for p in (_ROOT / "claude-plugin" / "skills").glob("*/SKILL.md")
    }
    assert committed == bundled
