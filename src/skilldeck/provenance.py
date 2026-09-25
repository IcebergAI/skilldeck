"""Release and bundled-skill provenance metadata.

The structures here deliberately answer only distribution-identity questions.
The richer, compatibility-aware public catalog is a separate product contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from importlib.resources import files
from pathlib import Path
from typing import TypedDict

from . import __version__
from .adapters import ADAPTERS
from .registry import (
    BUNDLE_FILES,
    DEFAULT_SKILLS_DIR,
    Skill,
    discover_skills,
    is_link,
    link_kind,
)

SCHEMA_VERSION = 1
PACKAGE_NAME = "skilldeck"
REPOSITORY_URL = "https://github.com/IcebergAI/skilldeck"
PLUGIN_NAME = "skilldeck"
_CONTENT_MANIFEST = "_content_manifest.json"
_BUILD_METADATA = "_build_metadata.json"
_CANONICAL_DOMAIN = b"skilldeck-canonical-skill-v1\0"
_PLUGIN_CONTENT_DOMAIN = "skilldeck-claude-plugin-content-v1"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELEASE_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
# Hex digits of the plugin content digest kept in a development plugin
# version; 12, as Claude Code itself shortens archive and command digests.
PLUGIN_DIGEST_CHARS = 12


class ContentSkill(TypedDict):
    name: str
    version: str
    canonical_sha256: str
    meta_sha256: str
    body_sha256: str
    claude_rendered_sha256: str


class ContentManifest(TypedDict):
    schema_version: int
    package_version: str
    skills: list[ContentSkill]


class BuildMetadata(TypedDict):
    schema_version: int
    source_repository: str
    source_ref: str | None
    source_commit: str | None


class PluginRelease(TypedDict):
    """The plugin content prepared as release ``version`` (``None``: none yet)."""

    schema_version: int
    version: str
    content_sha256: str | None


class DistributionSkill(TypedDict):
    name: str
    version: str
    canonical_sha256: str


class Distribution(TypedDict):
    name: str
    version: str
    source_repository: str
    source_ref: str | None
    source_commit: str | None


class DistributionProvenance(TypedDict):
    schema_version: int
    distribution: Distribution
    skills: list[DistributionSkill]


def normalise_text(text: str) -> str:
    """Use one cross-platform newline representation before hashing text."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sha256_text(text: str) -> str:
    digest = hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def canonical_skill_digest(meta_text: str, body_text: str) -> str:
    """Hash unambiguous, domain-separated canonical metadata and body bytes."""
    digest = hashlib.sha256()
    digest.update(_CANONICAL_DOMAIN)
    for label, text in ((b"meta.yaml", meta_text), (b"skill.md", body_text)):
        payload = normalise_text(text).encode("utf-8")
        digest.update(len(label).to_bytes(4, "big"))
        digest.update(label)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


def content_manifest(
    package_version: str,
    skills: Iterable[Skill] | None = None,
) -> ContentManifest:
    """Build the deterministic identity shared by Python and plugin outputs."""
    selected = list(skills or discover_skills(known_agents=set(ADAPTERS)))
    selected.sort(key=lambda skill: skill.name)
    names = [skill.name for skill in selected]
    if len(names) != len(set(names)):
        raise ValueError("duplicate skill name in content manifest")

    claude = ADAPTERS["claude"]
    records: list[ContentSkill] = []
    for skill in selected:
        meta_text = (skill.path / "meta.yaml").read_text(encoding="utf-8")
        records.append(
            {
                "name": skill.name,
                "version": skill.version,
                "canonical_sha256": canonical_skill_digest(meta_text, skill.body),
                "meta_sha256": sha256_text(meta_text),
                "body_sha256": sha256_text(skill.body),
                "claude_rendered_sha256": sha256_text(claude.render(skill)),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "package_version": package_version,
        "skills": records,
    }


def claude_plugin_metadata(
    plugin_version: str, skills: Iterable[Skill]
) -> dict[str, object]:
    """Return the exact generated Claude plugin metadata contract."""
    selected = sorted(skills, key=lambda skill: skill.name)
    description = "Security and code-review skills for Claude Code: " + ", ".join(
        skill.name for skill in selected
    )
    return {
        "name": PLUGIN_NAME,
        "version": plugin_version,
        "description": description,
        "author": {"name": "Richard Hope", "url": REPOSITORY_URL},
        "homepage": REPOSITORY_URL,
        "repository": REPOSITORY_URL,
        "license": "MIT",
        "keywords": ["security", "code-review", "skills"],
    }


def canonical_json(data: object) -> str:
    """Serialize generated provenance deterministically with one final newline."""
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def claude_plugin_content_digest(
    metadata: Mapping[str, object], files: Mapping[str, str]
) -> str:
    """Hash a generated Claude plugin tree, independent of its version string.

    ``metadata`` is the ``plugin.json`` object (its ``version`` is ignored) and
    ``files`` maps every other plugin-relative path, except the release record
    that stores this digest, to its text.
    """
    payload = {
        "domain": _PLUGIN_CONTENT_DOMAIN,
        "plugin": {key: value for key, value in metadata.items() if key != "version"},
        "files": {path: sha256_text(text) for path, text in files.items()},
    }
    return sha256_text(canonical_json(payload))


def parse_plugin_release(data: object) -> PluginRelease:
    """Validate a decoded ``claude-plugin/.skilldeck/release.json`` record."""
    if not isinstance(data, dict) or set(data) != {
        "schema_version",
        "version",
        "content_sha256",
    }:
        raise ValueError("plugin release record has unknown or missing fields")
    digest = data["content_sha256"]
    if (
        data["schema_version"] != SCHEMA_VERSION
        or not isinstance(data["version"], str)
        or not _RELEASE_VERSION_RE.fullmatch(data["version"])
        or not (
            digest is None or (isinstance(digest, str) and _DIGEST_RE.fullmatch(digest))
        )
    ):
        raise ValueError("plugin release record is malformed")
    return {
        "schema_version": SCHEMA_VERSION,
        "version": data["version"],
        "content_sha256": digest,
    }


def claude_plugin_version(
    package_version: str, content_sha256: str, release: PluginRelease
) -> str:
    """Return the plugin version Claude Code compares to decide on an update.

    Claude Code updates an installed plugin only when this string changes, so
    it is the exact package version only while the plugin content is the
    content prepared for that release. Any other content gets a development
    version that names its digest: a SemVer pre-release of the next patch,
    which sorts after the last release and before the next one.
    """
    if release["version"] == package_version and (
        release["content_sha256"] == content_sha256
    ):
        return package_version
    match = _RELEASE_VERSION_RE.fullmatch(package_version)
    if not match or not content_sha256.startswith("sha256:"):
        raise ValueError("plugin version needs a MAJOR.MINOR.PATCH package version")
    major, minor, patch = match.groups()
    digest = content_sha256.removeprefix("sha256:")[:PLUGIN_DIGEST_CHARS]
    return f"{major}.{minor}.{int(patch) + 1}-dev.sha256-{digest}"


def _load_json_resource(name: str) -> object:
    try:
        return json.loads(files("skilldeck").joinpath(name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid packaged provenance resource: {name}") from exc


def load_content_manifest() -> ContentManifest:
    data = _load_json_resource(_CONTENT_MANIFEST)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported packaged content manifest")
    if data.get("package_version") != __version__:
        raise ValueError("content manifest version does not match installed package")
    skills = data.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ValueError("packaged content manifest has no skills")
    names = [record.get("name") for record in skills if isinstance(record, dict)]
    if len(names) != len(skills) or len(names) != len(set(names)):
        raise ValueError("packaged content manifest has invalid skill identities")
    return data  # type: ignore[return-value]


def load_build_metadata() -> BuildMetadata:
    data = _load_json_resource(_BUILD_METADATA)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported packaged build metadata")
    if data.get("source_repository") != REPOSITORY_URL:
        raise ValueError("unexpected source repository in build metadata")
    source_ref = data.get("source_ref")
    source_commit = data.get("source_commit")
    if source_ref is None or source_commit is None:
        if source_ref is not None or source_commit is not None:
            raise ValueError(
                "source ref and commit must both be available or unavailable"
            )
    else:
        if source_ref != f"refs/tags/v{__version__}":
            raise ValueError("source ref does not match installed package version")
        if not isinstance(source_commit, str) or not _COMMIT_RE.fullmatch(
            source_commit
        ):
            raise ValueError("invalid source commit in build metadata")
    return data  # type: ignore[return-value]


def verify_bundled_skills(skills_dir: Path | None = None) -> list[str]:
    """Recompute every bundled skill's canonical digest from the installed files.

    Returns one message per problem: a skill whose ``meta.yaml`` or
    ``skill.md`` no longer hashes to the packaged content manifest, a skill
    that is missing or unreadable, any skill directory the manifest does not
    list, any other entry in a skill directory (OS and editor leftovers
    included: this is the release-integrity check, stricter than loading a
    skill), and a skill directory, ``meta.yaml`` or ``skill.md`` that is a
    symlink or junction. An empty list means the installed skills are exactly
    the ones the manifest records.
    """
    root = skills_dir or DEFAULT_SKILLS_DIR
    records = {record["name"]: record for record in load_content_manifest()["skills"]}
    try:
        present = {
            child.name for child in root.iterdir() if not child.name.startswith(".")
        }
    except OSError as exc:
        return [f"cannot read bundled skills directory {root}: {exc}"]
    problems = [
        f"{name}: not listed in the packaged content manifest"
        for name in sorted(present - set(records))
    ]
    for name, record in sorted(records.items()):
        skill_dir = root / name
        try:
            entries = sorted(child.name for child in skill_dir.iterdir())
            meta_text = (skill_dir / "meta.yaml").read_text(encoding="utf-8")
            body_text = (skill_dir / "skill.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{name}: cannot read the bundled skill: {exc}")
            continue
        extras = [entry for entry in entries if entry not in BUNDLE_FILES]
        if extras:
            problems.append(f"{name}: unexpected file(s): {', '.join(extras)}")
        if is_link(skill_dir):
            problems.append(f"{name}: the skill directory is a {link_kind(skill_dir)}")
        problems.extend(
            f"{name}: {filename} is a {link_kind(skill_dir / filename)}"
            for filename in BUNDLE_FILES
            if is_link(skill_dir / filename)
        )
        if canonical_skill_digest(meta_text, body_text) != record["canonical_sha256"]:
            problems.append(
                f"{name}: installed files do not match canonical digest "
                f"{record['canonical_sha256']}"
            )
    return problems


def distribution_provenance() -> DistributionProvenance:
    """Return the narrow installed-distribution identity exposed by the CLI."""
    content = load_content_manifest()
    build = load_build_metadata()
    return {
        "schema_version": SCHEMA_VERSION,
        "distribution": {
            "name": PACKAGE_NAME,
            "version": __version__,
            "source_repository": build["source_repository"],
            "source_ref": build["source_ref"],
            "source_commit": build["source_commit"],
        },
        "skills": [
            {
                "name": record["name"],
                "version": record["version"],
                "canonical_sha256": record["canonical_sha256"],
            }
            for record in content["skills"]
        ],
    }
