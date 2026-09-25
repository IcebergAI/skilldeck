#!/usr/bin/env python3
"""Require CHANGELOG lifecycle notes when a change affects compatibility.

``docs/lifecycle.md`` is the policy; this script checks the parts of it that a
machine can. With ``--base <ref>`` (a PR's target branch; CI's ``lint`` job
passes ``origin/<target>``), it compares the working tree with that ref:

- a skill directory removed: a ``### Removed`` entry naming the skill. The
  skill must also be ``deprecated`` in its ``meta.yaml`` at the base and, if a
  release tag contains the skill, a release must have published the
  deprecation at least ``NOTICE_DAYS`` ago (``NOTICE_DAYS_STABLE`` from 1.0):
  a tag whose own ``meta.yaml`` marks the skill deprecated and whose own
  CHANGELOG has a ``### Deprecated`` entry naming it, counted from the later of
  that section's date and the tag's date. The urgent security path skips the
  deprecation and the notice: the ``### Removed`` entry is marked
  ``**Security:**`` and a ``### Security`` entry names the skill too;
- a skill newly ``deprecated``: a ``### Deprecated`` entry naming it;
- a skill no longer listing an agent in ``supported-agents``: one
  ``### Removed`` entry naming the skill and the agent (an agent whose adapter
  is gone altogether is covered by the next rule instead);
- an adapter removed (named in the base's adapter contracts, missing from
  ``ALL_ADAPTERS`` now): a ``### Removed`` entry naming it and no skill;
- a skill's major version raised: a ``### Changed``, ``### Removed`` or
  ``### Security`` entry naming the skill and its new version;
- the catalog's ``schema_version`` changed: a ``**Breaking:**`` entry that
  mentions ``schema_version``.

Each entry must be a bullet in a section this change adds: ``## [Unreleased]``,
or a dated section the base's CHANGELOG does not have yet (a release cut in
the same change). It must name the skill, agent or adapter in backticks of its
own, e.g. `` `old-review` ``. Without release tags the notice rules can't be
checked; the script says so and carries on.

With or without ``--base`` it also checks the newest dated CHANGELOG section's
version against the one before it: a section with ``### Removed`` or
``### Deprecated`` entries, or an entry marked ``**Breaking``, must not be a
patch release (and, from 1.0, Removed or Breaking needs a major).

Needs PyYAML and the ``skilldeck`` package from this checkout, so run it with
``uv run --locked --extra dev python scripts/check_lifecycle.py``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))  # run from a checkout without installing
sys.path.insert(0, str(ROOT / "scripts"))

import _pyproject  # noqa: E402
import check_release_consistency as consistency  # noqa: E402

from skilldeck.adapters import ALL_ADAPTERS  # noqa: E402

#: minimum days between the release that announces a removal and the
#: removal: before 1.0, and from 1.0 (see docs/lifecycle.md#removing-a-skill)
NOTICE_DAYS = 90
NOTICE_DAYS_STABLE = 180
SKILLS_PATH = "src/skilldeck/skills"
CONTRACTS_PATH = "tests/fixtures/adapter-contracts/contracts.json"
CATALOG_SCHEMA_PATH = "src/skilldeck/catalog.schema.json"
POLICY = "docs/lifecycle.md"
#: marks the ``### Removed`` entry of an urgent security removal
SECURITY_MARK = "**Security:**"
NO_TAGS_NOTE = (
    "no release tags found; notice-period rules skipped — run "
    "`git fetch --tags` if there should be some"
)

_SECTION_RE = re.compile(
    r"## \[(?P<version>Unreleased|\d+\.\d+\.\d+)\]"
    r"(?:\s*-\s*(?P<date>\d{4}-\d{2}-\d{2}))?"
)
_GROUP_RE = re.compile(r"^### +(.+?)\s*$", re.MULTILINE)
_ENTRY_RE = re.compile(r"^[-*] ", re.MULTILINE)


class ChangelogError(ValueError):
    """A CHANGELOG this script cannot read."""


# --- the CHANGELOG ------------------------------------------------------------


@dataclass
class Section:
    """One ``## [...]`` section: its entries, by ``### Group``."""

    version: str | None  # None for [Unreleased]
    date: datetime.date | None
    groups: dict[str, list[str]] = field(default_factory=dict)

    def entries(self, *groups: str) -> list[str]:
        """The bullets under ``groups`` (all of them when none are given)."""
        names = groups or tuple(self.groups)
        return [entry for name in names for entry in self.groups.get(name, [])]


def parse_changelog(text: str, source: str = "CHANGELOG.md") -> list[Section]:
    """Every ``## [Unreleased]`` or ``## [x.y.z]`` section, in file order.

    Entries are the top-level ``-`` bullets, each with its indented
    continuation lines and sub-bullets. Group names are title-cased, so
    ``### removed`` counts as ``Removed``. A section dated with a day that
    does not exist raises :class:`ChangelogError` naming ``source``.
    """
    sections: list[Section] = []
    text = text.replace("\r\n", "\n")
    for chunk in re.split(r"^(?=## \[)", text, flags=re.MULTILINE):
        header = _SECTION_RE.match(chunk)
        if not header:
            continue  # the preamble, or a heading this parser does not know
        version = header.group("version")
        date = header.group("date")
        try:
            day = datetime.date.fromisoformat(date) if date else None
        except ValueError:
            raise ChangelogError(
                f"{source}: `{header.group(0)}` has an invalid date; use a real "
                "YYYY-MM-DD day"
            ) from None
        section = Section(
            version=None if version == "Unreleased" else version, date=day
        )
        parts = _GROUP_RE.split(chunk)
        # parts: [before the first group, name, body, name, body, ...]
        for name, body in zip(parts[1::2], parts[2::2], strict=True):
            entries = [e.strip() for e in _ENTRY_RE.split(body)[1:] if e.strip()]
            section.groups.setdefault(name.strip().title(), []).extend(entries)
        sections.append(section)
    return sections


def recent_sections(
    sections: list[Section], base_versions: Collection[str]
) -> list[Section]:
    """The sections a change adds: ``[Unreleased]``, and any dated section
    whose version the base's CHANGELOG (``base_versions``) does not have.

    A note belongs in ``[Unreleased]``. A change that also cuts a release
    (``scripts/prepare_release.py``) moves it into a new dated section, so
    that section counts too; one the base already has was published before
    and does not.
    """
    recent = [s for s in sections if s.version is None][:1]
    return recent + [s for s in _dated(sections) if s.version not in base_versions]


def _dated(sections: list[Section]) -> list[Section]:
    """The dated ``## [x.y.z] - DATE`` sections, oldest version first."""
    return sorted(
        (s for s in sections if s.version is not None and s.date is not None),
        key=lambda s: consistency.version_key(s.version or "0.0.0"),
    )


def names(entry: str, *terms: str) -> bool:
    """Whether ``entry`` names every one of ``terms`` in backticks."""
    return all(f"`{term}`" in entry for term in terms)


def mentions_version(entry: str, version: str) -> bool:
    """Whether ``entry`` gives ``version`` as a whole version, not part of one
    (``2.0.0`` is not in ``12.0.0`` or ``2.0.01``; a full stop may follow)."""
    pattern = rf"(?<!\d)(?<!\d\.){re.escape(version)}(?!\d|\.\d)"
    return re.search(pattern, entry) is not None


def _entries(recent: list[Section], *groups: str) -> list[str]:
    return [entry for section in recent for entry in section.entries(*groups)]


def _recorded(recent: list[Section], groups: tuple[str, ...], *terms: str) -> bool:
    return any(names(entry, *terms) for entry in _entries(recent, *groups))


def urgent_removal(recent: list[Section], name: str) -> bool:
    """Whether skill ``name`` is removed on the urgent security path: its
    ``### Removed`` entry is marked ``**Security:**`` and a ``### Security``
    entry names it too."""
    marked = any(
        names(entry, name) and SECURITY_MARK in entry
        for entry in _entries(recent, "Removed")
    )
    return marked and _recorded(recent, ("Security",), name)


# --- skills, adapters and the catalog at a ref or in the working tree ---------


@dataclass(frozen=True)
class SkillFacts:
    """The parts of a skill's ``meta.yaml`` the lifecycle rules look at."""

    version: str | None
    agents: frozenset[str]
    deprecated: bool


def skill_facts(meta_text: str) -> SkillFacts:
    """Read ``meta_text`` leniently: the registry validates it elsewhere."""
    try:
        data = yaml.safe_load(meta_text)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        return SkillFacts(version=None, agents=frozenset(), deprecated=False)
    version = data.get("version")
    agents = data.get("supported-agents")
    return SkillFacts(
        version=version if isinstance(version, str) else None,
        agents=frozenset(agent for agent in (agents or []) if isinstance(agent, str))
        if isinstance(agents, list)
        else frozenset(),
        deprecated=isinstance(data.get("deprecated"), dict),
    )


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, check=False
    )


def _git_text(ref: str, path: str) -> str | None:
    """``path`` as committed at ``ref``, or None if it is not there."""
    if _git("cat-file", "-e", f"{ref}:{path}").returncode != 0:
        return None
    return _git("show", f"{ref}:{path}").stdout.decode("utf-8", "replace")


def skills_at(ref: str) -> dict[str, SkillFacts]:
    """Each skill directory with a ``meta.yaml`` at ``ref``."""
    listing = _git("ls-tree", "-z", "--name-only", ref, "--", f"{SKILLS_PATH}/")
    skills = {}
    for path in listing.stdout.decode("utf-8").split("\0"):
        name = path.rpartition("/")[2]
        if not name or name.startswith("."):
            continue
        meta = _git_text(ref, f"{path}/meta.yaml")
        if meta is not None:
            skills[name] = skill_facts(meta)
    return skills


def skills_now() -> dict[str, SkillFacts]:
    """Each skill directory with a ``meta.yaml`` in the working tree."""
    root = ROOT / SKILLS_PATH
    if not root.is_dir():
        return {}
    return {
        meta.parent.name: skill_facts(meta.read_text(encoding="utf-8"))
        for meta in sorted(root.glob("*/meta.yaml"))
        if not meta.parent.name.startswith(".")
    }


def adapters_at(ref: str) -> set[str] | None:
    """The adapter names in the adapter contracts at ``ref``.

    ``tests/test_adapter_contracts.py`` keeps that file's adapters equal to
    ``ALL_ADAPTERS``, so it records which adapters the base shipped without
    importing the base's code. None if the base predates the contracts.
    """
    text = _git_text(ref, CONTRACTS_PATH)
    if text is None:
        return None
    try:
        adapters = json.loads(text)["adapters"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return set(adapters) if isinstance(adapters, dict) else None


def _schema_version(text: str | None) -> object:
    if text is None:
        return None
    try:
        return json.loads(text)["properties"]["schema_version"]["const"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


# --- release tags ---------------------------------------------------------------


@dataclass(frozen=True)
class Tag:
    """A ``vX.Y.Z`` release tag reachable from the base."""

    ref: str
    date: datetime.date | None  # the tag's own date (a lightweight tag's commit's)

    @property
    def name(self) -> str:
        return self.ref.removeprefix("refs/tags/")


def release_tags(base: str) -> list[Tag]:
    """Every exact ``vX.Y.Z`` tag reachable from ``base``: a release tag must
    be on ``main``, so one elsewhere was never a release."""
    listing = _git(
        "for-each-ref",
        f"--merged={base}",
        "--format=%(refname) %(creatordate:short)",
        "refs/tags/v*",
    ).stdout.decode("utf-8")
    tags = []
    for line in listing.splitlines():
        ref, _, day = line.partition(" ")
        try:
            consistency.normalize_tag(ref)
        except ValueError:
            continue
        try:
            date = datetime.date.fromisoformat(day)
        except ValueError:
            date = None
        tags.append(Tag(ref, date))
    return tags


def released(name: str, tags: Iterable[Tag]) -> bool:
    """Whether any of ``tags`` contains skill ``name``."""
    path = f"{SKILLS_PATH}/{name}/meta.yaml"
    return any(_git("cat-file", "-e", f"{t.ref}:{path}").returncode == 0 for t in tags)


def deprecation_published(
    name: str, tags: Iterable[Tag]
) -> tuple[datetime.date, Tag] | None:
    """When a release first published skill ``name``'s deprecation, and which.

    A tag counts only if its own ``meta.yaml`` marks the skill deprecated and
    its own CHANGELOG has a dated ``### Deprecated`` entry naming it; the
    notice starts at the later of that section's date and the tag's date, so
    neither a Deprecated entry added to an old section afterwards nor an old
    section date on a late tag shortens it.
    """
    starts = []
    for tag in tags:
        meta = _git_text(tag.ref, f"{SKILLS_PATH}/{name}/meta.yaml")
        log = _git_text(tag.ref, "CHANGELOG.md")
        if meta is None or log is None or tag.date is None:
            continue
        if not skill_facts(meta).deprecated:
            continue
        dates = [
            section.date
            for section in _dated(parse_changelog(log, f"{tag.name}:CHANGELOG.md"))
            if section.date is not None
            and any(names(entry, name) for entry in section.entries("Deprecated"))
        ]
        if dates:
            starts.append((max(min(dates), tag.date), tag))
    return min(starts, key=lambda start: start[0]) if starts else None


# --- the rules -----------------------------------------------------------------


def _where(group: str, *terms: str) -> str:
    named = " and ".join(f"`{term}`" for term in terms)
    article, named = ("one", f"both {named}") if len(terms) > 1 else ("a", named)
    return (
        f"add {article} `### {group}` entry naming {named} (in backticks) under "
        "`## [Unreleased]` in CHANGELOG.md"
    )


def notice_days() -> int:
    """The notice period for the project version (the stricter one if the
    version cannot be read)."""
    try:
        major = consistency.version_key(_pyproject.project_version(ROOT))[0]
    except (_pyproject.PyprojectError, ValueError):
        return NOTICE_DAYS_STABLE
    return NOTICE_DAYS if major == 0 else NOTICE_DAYS_STABLE


def _notice_error(name: str, tags: list[Tag], today: datetime.date, days: int) -> str:
    """Why removing skill ``name`` today breaks the notice rule, or ``""``."""
    published = deprecation_published(name, tags)
    if published is None:
        return (
            f"skill `{name}` was removed, but no release published its "
            "deprecation: a tagged release must mark it `deprecated` and have "
            f"a `### Deprecated` entry naming `{name}` at least {days} days "
            f"before the removal ({POLICY}#removing-a-skill)"
        )
    start, tag = published
    allowed = start + datetime.timedelta(days=days)
    if today < allowed:
        return (
            f"skill `{name}` was removed too early: {tag.name} published its "
            f"deprecation on {start.isoformat()}, so it can be removed from "
            f"{allowed.isoformat()} ({days} days' notice; "
            f"{POLICY}#removing-a-skill)"
        )
    return ""


def _major(version: str) -> int:
    """The MAJOR of ``version``; -1 if it is not MAJOR.MINOR.PATCH (the
    registry rejects that, so no major bump is inferred from it)."""
    try:
        return consistency.version_key(version)[0]
    except ValueError:
        return -1


def skill_errors(
    base: dict[str, SkillFacts],
    head: dict[str, SkillFacts],
    recent: list[Section],
    adapters: Iterable[str],
    today: datetime.date,
    tags: list[Tag],
    days: int = NOTICE_DAYS,
) -> list[str]:
    """Lifecycle notes missing for the skill changes from ``base`` to ``head``.

    ``recent`` are the CHANGELOG sections the change adds, ``tags`` the
    release tags reachable from the base, and ``days`` the notice period.
    """
    adapters = set(adapters)
    errors = []
    for name in sorted(base.keys() - head.keys()):
        if not _recorded(recent, ("Removed",), name):
            errors.append(
                f"skill `{name}` was removed: {_where('Removed', name)}, saying "
                "what replaces it and how to delete installed copies "
                f"({POLICY}#removing-a-skill)"
            )
        if urgent_removal(recent, name):
            continue  # the urgent path: no deprecation or notice period
        if not base[name].deprecated:
            errors.append(
                f"skill `{name}` was removed without being deprecated first: "
                "mark it `deprecated` in its meta.yaml, release that, and "
                f"remove it after the notice period ({POLICY}#removing-a-skill). "
                f"An urgent security removal instead marks its `### Removed` "
                f"entry `{SECURITY_MARK}` and adds a `### Security` entry "
                f"naming `{name}` ({POLICY}#security-fixes)"
            )
        elif released(name, tags):
            notice = _notice_error(name, tags, today, days)
            if notice:
                errors.append(notice)
    for name in sorted(base.keys() & head.keys()):
        old, new = base[name], head[name]
        if old.version is None or new.version is None:
            continue  # unreadable meta.yaml: the registry's tests report it
        newly_deprecated = new.deprecated and not old.deprecated
        if newly_deprecated and not _recorded(recent, ("Deprecated",), name):
            errors.append(
                f"skill `{name}` is newly deprecated: "
                f"{_where('Deprecated', name)}, naming its replacement or the "
                f"reason ({POLICY}#deprecating-a-skill)"
            )
        for agent in sorted(old.agents - new.agents):
            if agent not in adapters:
                continue  # the adapter itself is gone: adapter_errors covers it
            if not _recorded(recent, ("Removed",), name, agent):
                errors.append(
                    f"skill `{name}` no longer supports `{agent}`: "
                    f"{_where('Removed', name, agent)}, "
                    f"telling users to run `skilldeck uninstall {name} --agent "
                    f"{agent}` ({POLICY}#dropping-an-agent-from-a-skill)"
                )
        if _major(new.version) > _major(old.version) and not any(
            names(entry, name) and mentions_version(entry, new.version)
            for entry in _entries(recent, "Changed", "Removed", "Security")
        ):
            errors.append(
                f"skill `{name}` went from {old.version} to {new.version}, a "
                "major (breaking) change: add a `### Changed` entry naming "
                f"`{name}` and {new.version} under `## [Unreleased]` in "
                "CHANGELOG.md, saying what changed and what users should do "
                f"({POLICY}#skill-versions)"
            )
    return errors


def adapter_errors(
    base: set[str] | None,
    head: Iterable[str],
    recent: list[Section],
    skills: Collection[str],
) -> list[str]:
    """Lifecycle notes missing for adapters removed since ``base``.

    The entry must name the adapter and none of ``skills``, so a per-skill
    "``x`` no longer supports ``agent``" entry doesn't count as the note that
    the adapter itself is gone.
    """
    if base is None:
        return []
    return [
        f"adapter `{name}` was removed: add a `### Removed` entry of its own "
        f"naming `{name}` (in backticks) and no skill under `## [Unreleased]` "
        "in CHANGELOG.md, listing the paths it installed to so users can "
        f"delete what is left ({POLICY}#removing-an-agent-or-format)"
        for name in sorted(base - set(head))
        if not any(
            names(entry, name) and not any(names(entry, s) for s in skills)
            for entry in _entries(recent, "Removed")
        )
    ]


def catalog_errors(base: object, head: object, recent: list[Section]) -> list[str]:
    """A catalog ``schema_version`` change needs a **Breaking:** entry."""
    if base is None or head is None or base == head:
        return []
    if any(
        "**Breaking" in entry and "`schema_version`" in entry
        for entry in _entries(recent)
    ):
        return []
    return [
        f"the catalog schema_version changed from {base} to {head}: add a "
        "`**Breaking:**` entry mentioning `schema_version` under "
        "`## [Unreleased]` in CHANGELOG.md, saying what consumers must change "
        "(docs/catalog.md#compatibility-rules)"
    ]


def release_bump_errors(sections: list[Section]) -> list[str]:
    """The newest dated section must be a big enough version bump.

    Removals and **Breaking** changes need a minor release before 1.0 and a
    major one after; deprecations need at least a minor release. So a patch
    release is always safe to take.
    """
    dated = _dated(sections)
    if len(dated) < 2:
        return []
    previous, newest = dated[-2], dated[-1]
    assert previous.version is not None and newest.version is not None
    old = consistency.version_key(previous.version)
    new = consistency.version_key(newest.version)
    kinds = {
        "### Removed": bool(newest.entries("Removed")),
        "**Breaking**": any("**Breaking" in e for e in newest.entries()),
        "### Deprecated": bool(newest.entries("Deprecated")),
    }
    breaking = kinds["### Removed"] or kinds["**Breaking**"]
    if new[0] > old[0]:
        return []
    if breaking and new[0] > 0:
        needed = f"a major release ({new[0] + 1}.0.0)"
    elif (breaking or kinds["### Deprecated"]) and new[:2] == old[:2]:
        needed = f"a minor release ({new[0]}.{new[1] + 1}.0)"
    else:
        return []
    found = ", ".join(kind for kind, present in kinds.items() if present)
    return [
        f"CHANGELOG.md's newest release {newest.version} follows "
        f"{previous.version} but has {found} entries, which need {needed}: "
        f"prepare that version instead ({POLICY}#the-package)"
    ]


def lifecycle_check(
    base: str, today: datetime.date | None = None
) -> tuple[list[str], list[str]]:
    """The lifecycle notes the change from ``base`` to the working tree lacks,
    and any notes about what could not be checked.

    Raises :class:`ChangelogError` if a CHANGELOG it needs cannot be read.
    """
    if today is None:
        today = datetime.datetime.now(datetime.timezone.utc).date()
    try:
        in_git = _git("rev-parse", "--git-dir").returncode == 0
    except OSError:
        in_git = False
    if not in_git:
        return [f"--base {base} needs a git checkout"], []
    if _git("rev-parse", "-q", "--verify", f"{base}^{{commit}}").returncode != 0:
        return [f"base ref {base!r} not found (fetch it first)"], []
    sections = parse_changelog((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    base_log = _git_text(base, "CHANGELOG.md")
    base_versions = {
        s.version
        for s in parse_changelog(base_log or "", f"{base}:CHANGELOG.md")
        if s.version is not None
    }
    recent = recent_sections(sections, base_versions)
    tags = release_tags(base)
    base_skills, head_skills = skills_at(base), skills_now()
    head_schema = ROOT / CATALOG_SCHEMA_PATH
    errors = [
        *skill_errors(
            base_skills,
            head_skills,
            recent,
            ALL_ADAPTERS,
            today,
            tags,
            notice_days(),
        ),
        *adapter_errors(
            adapters_at(base), ALL_ADAPTERS, recent, base_skills.keys() | head_skills
        ),
        *catalog_errors(
            _schema_version(_git_text(base, CATALOG_SCHEMA_PATH)),
            _schema_version(
                head_schema.read_text(encoding="utf-8")
                if head_schema.is_file()
                else None
            ),
            recent,
        ),
    ]
    return errors, ([] if tags else [NO_TAGS_NOTE])


def lifecycle_errors(base: str, today: datetime.date | None = None) -> list[str]:
    """Every lifecycle note the change from ``base`` to the working tree lacks."""
    return lifecycle_check(base, today)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        help="git ref this change will merge into (a PR's target branch): "
        "require CHANGELOG notes for the compatibility changes since it",
    )
    args = parser.parse_args(argv)

    notes: list[str] = []
    try:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        errors = release_bump_errors(parse_changelog(changelog))
        if args.base:
            found, notes = lifecycle_check(args.base)
            errors += found
    except ChangelogError as exc:
        errors = [str(exc)]
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        print(
            f"\nSee {POLICY}: a compatibility change needs a CHANGELOG entry "
            "naming what\nchanged (in backticks), under [Unreleased].",
            file=sys.stderr,
        )
        return 1
    target = f"the changes since {args.base}" if args.base else "the newest release"
    print(f"ok: lifecycle notes cover {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
