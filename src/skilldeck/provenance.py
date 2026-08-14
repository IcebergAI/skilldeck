"""Release and bundled-skill provenance metadata.

The structures here deliberately answer only distribution-identity questions.
The richer, compatibility-aware public catalog is a separate product contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from importlib.resources import files
from typing import TypedDict

from . import __version__
from .adapters import ADAPTERS
from .registry import Skill, discover_skills

SCHEMA_VERSION = 1
PACKAGE_NAME = "skilldeck"
REPOSITORY_URL = "https://github.com/IcebergAI/skilldeck"
PLUGIN_NAME = "skilldeck"
_CONTENT_MANIFEST = "_content_manifest.json"
_BUILD_METADATA = "_build_metadata.json"
_CANONICAL_DOMAIN = b"skilldeck-canonical-skill-v1\0"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


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
    package_version: str, skills: Iterable[Skill]
) -> dict[str, object]:
    """Return the exact generated Claude plugin metadata contract."""
    selected = sorted(skills, key=lambda skill: skill.name)
    description = "Security and code-review skills for Claude Code: " + ", ".join(
        skill.name for skill in selected
    )
    return {
        "name": PLUGIN_NAME,
        "version": package_version,
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
