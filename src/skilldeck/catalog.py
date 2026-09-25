"""The public, machine-readable catalog of bundled skills.

Unlike the narrow provenance record, the catalog is a compatibility-aware
product contract: ``CATALOG_SCHEMA_VERSION`` and the JSON Schema shipped next
to this module (``catalog.schema.json``) describe it, and docs/catalog.md sets
the rules for changing it. Every skill's ``canonical_sha256`` is recomputed
from the skill files and must equal the packaged content manifest's record,
the digest ``skilldeck provenance --verify`` checks; ``rendered_sha256`` gives,
per native agent, the ``hash=`` an install stamp records for that agent's file.
``capabilities`` is the skill's capability declaration (see ``capabilities``).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from importlib.resources import files
from typing import TypedDict

from .adapters import ADAPTERS
from .capabilities import CapabilityRecord
from .provenance import (
    REPOSITORY_URL,
    ContentManifest,
    Distribution,
    canonical_skill_digest,
    distribution_provenance,
    load_content_manifest,
)
from .registry import Skill
from .stamp import content_hash

# Bump only for a breaking change; see docs/catalog.md.
CATALOG_SCHEMA_VERSION = 1
CATALOG_SCHEMA_RESOURCE = "catalog.schema.json"
# Where the canonical skills live in the source repository, as a POSIX path.
SKILLS_SOURCE_PATH = "src/skilldeck/skills"


class CatalogDeprecation(TypedDict):
    since: str
    replacement: str | None
    reason: str


class CatalogSource(TypedDict):
    repository: str
    path: str


class CatalogSkill(TypedDict):
    name: str
    version: str
    category: str
    description: str
    supported_agents: list[str]
    canonical_sha256: str
    rendered_sha256: dict[str, str]
    source: CatalogSource
    deprecated: CatalogDeprecation | None
    capabilities: CapabilityRecord


class Catalog(TypedDict):
    schema_version: int
    distribution: Distribution
    skills: list[CatalogSkill]


class CatalogError(ValueError):
    """The skills disagree with the packaged content manifest."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def _entry(skill: Skill, digest: str) -> CatalogSkill:
    deprecated: CatalogDeprecation | None = None
    if skill.deprecated is not None:
        deprecated = {
            "since": skill.deprecated.since,
            "replacement": skill.deprecated.replacement,
            "reason": skill.deprecated.reason,
        }
    return {
        "name": skill.name,
        "version": skill.version,
        "category": skill.category,
        "description": skill.description,
        "supported_agents": sorted(skill.supported_agents),
        "canonical_sha256": digest,
        "rendered_sha256": {
            name: f"sha256:{content_hash(adapter.render(skill))}"
            for name, adapter in sorted(ADAPTERS.items())
            if adapter.supports(skill)
        },
        "source": {
            "repository": REPOSITORY_URL,
            "path": f"{SKILLS_SOURCE_PATH}/{skill.name}",
        },
        "deprecated": deprecated,
        "capabilities": skill.capabilities.record(),
    }


def build_catalog(
    skills: Iterable[Skill], manifest: ContentManifest | None = None
) -> Catalog:
    """Return the catalog of ``skills``, sorted by name.

    Each skill's canonical digest is recomputed from its files and checked
    against ``manifest`` (by default the packaged content manifest), which must
    list exactly these skills; any disagreement raises :class:`CatalogError`,
    so the catalog never vouches for content the package did not ship.
    """
    selected = sorted(skills, key=lambda skill: skill.name)
    if manifest is None:
        manifest = load_content_manifest()
    recorded = {
        record["name"]: record["canonical_sha256"] for record in manifest["skills"]
    }
    problems: list[str] = []
    entries: list[CatalogSkill] = []
    seen: set[str] = set()
    for skill in selected:
        if skill.name in seen:
            problems.append(f"{skill.name}: found more than once")
            continue
        seen.add(skill.name)
        try:
            meta_text = (skill.path / "meta.yaml").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{skill.name}: cannot read meta.yaml: {exc}")
            continue
        digest = canonical_skill_digest(meta_text, skill.body)
        expected = recorded.get(skill.name)
        if expected is None:
            problems.append(f"{skill.name}: not listed in the content manifest")
        elif digest != expected:
            problems.append(
                f"{skill.name}: skill files do not match canonical digest {expected}"
            )
        entries.append(_entry(skill, digest))
    problems.extend(
        f"{name}: listed in the content manifest but not bundled"
        for name in sorted(set(recorded) - seen)
    )
    if problems:
        raise CatalogError(problems)
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "distribution": distribution_provenance()["distribution"],
        "skills": entries,
    }


def filter_catalog(
    catalog: Catalog, categories: Collection[str], agents: Collection[str]
) -> Catalog:
    """Keep the skills in any of ``categories`` that support all of ``agents``.

    An empty collection does not filter on that field.
    """
    return {
        **catalog,
        "skills": [
            skill
            for skill in catalog["skills"]
            if (not categories or skill["category"] in categories)
            and all(agent in skill["supported_agents"] for agent in agents)
        ],
    }


def catalog_schema_text() -> str:
    """Return the packaged JSON Schema for this catalog ``schema_version``."""
    return (
        files("skilldeck").joinpath(CATALOG_SCHEMA_RESOURCE).read_text(encoding="utf-8")
    )
