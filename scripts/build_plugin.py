#!/usr/bin/env python3
"""Generate the committed Claude Code plugin tree from the canonical skills.

Claude Code installs plugins from files committed to the repository, so the
plugin layout is generated and checked in rather than built on demand:

* ``.claude-plugin/marketplace.json`` -- the marketplace catalog, at repo root
* ``claude-plugin/.claude-plugin/plugin.json`` -- the plugin manifest
* ``claude-plugin/skills/<name>/SKILL.md`` -- every skill, rendered by the
  Claude adapter (identical to a ``skilldeck install --agent claude`` output,
  minus the install stamp)
* ``claude-plugin/.skilldeck/release.json`` -- the plugin content digest
  recorded when the current project version was prepared for release

Marketplace users install whatever ``main`` holds, and Claude Code updates an
installed plugin only when ``plugin.json``'s ``version`` string changes. So the
version is the project version only while the plugin content is exactly what
was prepared for that release; any other content gets a development version
naming its content digest (``0.3.1-dev.sha256-<12 hex>``). A project version
bump (``scripts/prepare_release.py``) records the content at that moment as the
release's. See ``docs/releasing.md``.

Run with no arguments to (re)write the tree; ``--check`` exits non-zero if the
committed tree differs from what would be generated (wired into pytest via
``tests/test_plugin_build.py``). The output depends only on the canonical
skills, the project version, and the committed release record, so ``--check``
is deterministic. Never edit the generated files by hand.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))  # run from a checkout without installing
sys.path.insert(0, str(ROOT / "scripts"))

import _pyproject  # noqa: E402

from skilldeck.adapters import ADAPTERS  # noqa: E402
from skilldeck.provenance import (  # noqa: E402
    SCHEMA_VERSION,
    PluginRelease,
    canonical_json,
    claude_plugin_content_digest,
    claude_plugin_metadata,
    claude_plugin_version,
    content_manifest,
    parse_plugin_release,
)
from skilldeck.registry import discover_skills  # noqa: E402

PLUGIN_NAME = "skilldeck"
MARKETPLACE_NAME = "skilldeck"
REPO_URL = "https://github.com/IcebergAI/skilldeck"
PLUGIN_DIR = Path("claude-plugin")
RELEASE_RECORD = PLUGIN_DIR / ".skilldeck" / "release.json"


def project_version(root: Path = ROOT) -> str:
    try:
        return _pyproject.project_version(root)
    except _pyproject.PyprojectError as exc:
        raise SystemExit(f"error: {exc}") from None


def read_release(root: Path = ROOT) -> PluginRelease | None:
    """Return the committed release record, or ``None`` if there is none."""
    path = root / RELEASE_RECORD
    if not path.exists():
        return None
    try:
        return parse_plugin_release(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SystemExit(
            f"error: cannot read {RELEASE_RECORD}: {exc}\n"
            f"If a merge left it conflicted, restore main's copy "
            f"(git checkout origin/main -- {RELEASE_RECORD.as_posix()}) and re-run."
        ) from None


def _release_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        raise SystemExit(f"error: {version!r} is not MAJOR.MINOR.PATCH") from None


def plugin_release(
    recorded: PluginRelease | None, version: str, content_sha256: str
) -> PluginRelease:
    """Return the release record the generated tree must carry.

    A newer project version than the record names is a release being prepared,
    so the current content becomes that release's content. Otherwise the record
    stands, and content that differs from it gets a development version. With
    no record, nothing is known to have been released under the current
    version, which also yields a development version.
    """
    if recorded is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": version,
            "content_sha256": None,
        }
    if recorded["version"] != version:
        if _release_key(version) < _release_key(recorded["version"]):
            # Recording here would label today's content with an old version
            # string that users may already hold with other content.
            raise SystemExit(
                f"error: project version {version} is older than the plugin "
                f"release record's {recorded['version']}; restore "
                f"{RELEASE_RECORD.as_posix()} together with pyproject.toml "
                "instead of regenerating it"
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "version": version,
            "content_sha256": content_sha256,
        }
    return recorded


def generate(root: Path = ROOT, skills_dir: Path | None = None) -> dict[Path, str]:
    """Return every generated file as ``repo-relative path -> content``."""
    version = project_version(root)
    skills = discover_skills(skills_dir, known_agents=set(ADAPTERS))
    claude = ADAPTERS["claude"]
    plugin_files = {
        f"skills/{skill.name}/SKILL.md": claude.render(skill) for skill in skills
    }
    manifest_text = canonical_json(content_manifest(version, skills))
    plugin_files[".skilldeck/content-manifest.json"] = manifest_text

    digest = claude_plugin_content_digest(
        claude_plugin_metadata(version, skills), plugin_files
    )
    release = plugin_release(read_release(root), version, digest)
    plugin = claude_plugin_metadata(
        claude_plugin_version(version, digest, release), skills
    )

    files = {PLUGIN_DIR / rel: text for rel, text in plugin_files.items()}
    files[PLUGIN_DIR / ".claude-plugin" / "plugin.json"] = (
        json.dumps(plugin, indent=2) + "\n"
    )
    files[RELEASE_RECORD] = canonical_json(release)
    marketplace = {
        "name": MARKETPLACE_NAME,
        "owner": {"name": "Richard Hope", "url": REPO_URL},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": f"./{PLUGIN_DIR.as_posix()}",
                "description": str(plugin["description"]),
            }
        ],
    }
    files[Path(".claude-plugin/marketplace.json")] = (
        json.dumps(marketplace, indent=2) + "\n"
    )
    files[Path("src/skilldeck/_content_manifest.json")] = manifest_text
    return files


def plugin_version(files: dict[Path, str]) -> str:
    """The ``plugin.json`` version in a :func:`generate` result."""
    plugin = json.loads(files[PLUGIN_DIR / ".claude-plugin" / "plugin.json"])
    return str(plugin["version"])


def stale(files: dict[Path, str], root: Path = ROOT) -> list[str]:
    """Differences between the generated files and the committed tree."""
    problems = []
    for rel, content in files.items():
        on_disk = root / rel
        if not on_disk.is_file():
            problems.append(f"missing: {rel.as_posix()}")
        elif on_disk.read_text(encoding="utf-8") != content:
            problems.append(f"outdated: {rel.as_posix()}")
    plugin_dir = root / PLUGIN_DIR
    if plugin_dir.is_dir():
        expected = {root / rel for rel in files if rel.is_relative_to(PLUGIN_DIR)}
        actual = {
            path
            for path in plugin_dir.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        for path in sorted(actual - expected):
            problems.append(f"unexpected: {path.relative_to(root).as_posix()}")
    return problems


def write(files: dict[Path, str], root: Path = ROOT) -> None:
    shutil.rmtree(root / PLUGIN_DIR / "skills", ignore_errors=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {rel}")
    print(f"plugin version: {plugin_version(files)}")


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
        print(
            f"ok: plugin tree is current ({len(files)} files, "
            f"plugin version {plugin_version(files)})"
        )
        return 0
    write(files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
