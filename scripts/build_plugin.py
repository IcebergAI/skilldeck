#!/usr/bin/env python3
"""Generate the committed Claude Code plugin tree from the canonical skills.

Claude Code installs plugins from files committed to the repository, so the
plugin layout is generated and checked in rather than built on demand:

* ``.claude-plugin/marketplace.json`` -- the marketplace catalog, at repo root
* ``claude-plugin/.claude-plugin/plugin.json`` -- the plugin manifest
* ``claude-plugin/skills/<name>/SKILL.md`` -- every skill, rendered by the
  Claude adapter (identical to a ``skilldeck install --agent claude`` output,
  minus the install stamp)

Run with no arguments to (re)write the tree; ``--check`` exits non-zero if the
committed tree differs from what would be generated (wired into pytest via
``tests/test_plugin_build.py``). Never edit the generated files by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))  # run from a checkout without installing

from skilldeck.adapters import ADAPTERS  # noqa: E402
from skilldeck.provenance import (  # noqa: E402
    canonical_json,
    claude_plugin_metadata,
    content_manifest,
)
from skilldeck.registry import discover_skills  # noqa: E402

PLUGIN_NAME = "skilldeck"
MARKETPLACE_NAME = "skilldeck"
REPO_URL = "https://github.com/IcebergAI/skilldeck"


def project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("error: no version in pyproject.toml")
    return match.group(1)


def generate() -> dict[Path, str]:
    """Return every generated file as ``repo-relative path -> content``."""
    skills = discover_skills(known_agents=set(ADAPTERS))
    claude = ADAPTERS["claude"]
    files: dict[Path, str] = {}
    for skill in skills:
        path = Path("claude-plugin/skills") / skill.name / "SKILL.md"
        files[path] = claude.render(skill)

    plugin = claude_plugin_metadata(project_version(), skills)
    description = str(plugin["description"])
    files[Path("claude-plugin/.claude-plugin/plugin.json")] = (
        json.dumps(plugin, indent=2) + "\n"
    )

    marketplace = {
        "name": MARKETPLACE_NAME,
        "owner": {"name": "Richard Hope", "url": REPO_URL},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": "./claude-plugin",
                "description": description,
            }
        ],
    }
    files[Path(".claude-plugin/marketplace.json")] = (
        json.dumps(marketplace, indent=2) + "\n"
    )
    manifest_text = canonical_json(content_manifest(project_version(), skills))
    files[Path("src/skilldeck/_content_manifest.json")] = manifest_text
    files[Path("claude-plugin/.skilldeck/content-manifest.json")] = manifest_text
    return files


def stale(files: dict[Path, str]) -> list[str]:
    """Differences between the generated files and the committed tree."""
    problems = []
    for rel, content in files.items():
        on_disk = ROOT / rel
        if not on_disk.is_file():
            problems.append(f"missing: {rel}")
        elif on_disk.read_text(encoding="utf-8") != content:
            problems.append(f"outdated: {rel}")
    plugin_dir = ROOT / "claude-plugin"
    if plugin_dir.is_dir():
        expected = {ROOT / rel for rel in files if rel.is_relative_to("claude-plugin")}
        actual = {
            path
            for path in plugin_dir.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        for path in sorted(actual - expected):
            problems.append(f"unexpected: {path.relative_to(ROOT)}")
    return problems


def write(files: dict[Path, str]) -> None:
    shutil.rmtree(ROOT / "claude-plugin" / "skills", ignore_errors=True)
    for rel, content in files.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed tree matches; write nothing",
    )
    args = parser.parse_args()
    files = generate()
    if args.check:
        problems = stale(files)
        if problems:
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            print("\nRegenerate with: python scripts/build_plugin.py", file=sys.stderr)
            return 1
        print(f"ok: plugin tree is current ({len(files)} files)")
        return 0
    write(files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
