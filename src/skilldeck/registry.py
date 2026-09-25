"""Discovery and loading of canonical skills.

A skill lives in ``skills/<name>/`` and is made of exactly two files:

* ``meta.yaml`` -- metadata (name, description, category, version, supported
  agents, capabilities, and an optional ``deprecated`` record)
* ``skill.md``  -- the agent-neutral skill body / prompt

This module turns those into :class:`Skill` objects. Adapters consume them to
render agent-specific output; nothing here knows about a particular agent.
Loading also enforces the bundle rules: nothing else in the directory (no
scripts, assets or symlinks), and no link in ``skill.md`` to a file the skill
would need to ship.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .capabilities import (
    SCRIPT_SUFFIXES,
    Capabilities,
    CapabilityError,
    parse_capabilities,
)

# Bundled ``skills/`` directory, co-located with this module inside the package.
# Resolving relative to ``__file__`` works identically for an editable checkout
# and an installed wheel, since hatchling ships the skill files alongside the code.
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

REQUIRED_FIELDS = (
    "name",
    "description",
    "category",
    "version",
    "supported-agents",
    "capabilities",
)
# Every key meta.yaml may carry; anything else (say, a misspelt ``depreciated``)
# is an error rather than silently ignored.
ALLOWED_FIELDS = (*REQUIRED_FIELDS, "deprecated")

# ``name`` and ``description`` limits follow the Agent Skills specification
# (https://agentskills.io/specification), the ``SKILL.md`` format the Claude
# adapter renders: 1-64 lowercase ASCII letters, digits and hyphens with no
# leading, trailing or doubled hyphen; a 1-1024 character description. Adapters
# also build file paths from ``name``, so the pattern doubles as a path-safety
# check.
NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
# A SemVer 2.0.0 normal version (https://semver.org/, item 2): MAJOR.MINOR.PATCH
# non-negative integers without leading zeroes.
_VERSION_PART = r"(?:0|[1-9][0-9]*)"
VERSION_RE = re.compile(rf"{_VERSION_PART}\.{_VERSION_PART}\.{_VERSION_PART}")
# ``deprecated`` is optional; absent means the skill is not deprecated.
DEPRECATION_FIELDS = ("since", "reason", "replacement")

#: everything a skill directory may hold. Skilldeck installs one file per
#: skill, so a bundle has no way to carry a script, an asset or a link, and a
#: skill's metadata cannot declare one.
BUNDLE_FILES = ("meta.yaml", "skill.md")
# Files an OS or editor leaves next to the ones you edit: macOS Finder and
# AppleDouble files, Windows thumbnail and folder settings, Python bytecode,
# and Emacs and Vim backup, lock, autosave and swap files. Loading a skill
# ignores them, so one stray file doesn't break every command;
# ``provenance --verify`` (the release-integrity check) still reports them.
_JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", "__pycache__"})
_JUNK_RE = re.compile(r"\._.*|\.#.*|.*~|#.*#|\..+\.sw[a-p]", re.S)
# Leading bytes of native binaries: ELF, PE (MZ) and Mach-O (32/64-bit, both
# byte orders, and universal).
_BINARY_MAGIC = (
    b"\x7fELF",
    b"MZ",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
)
# Markdown the link check must skip: fenced and indented code blocks, and
# code spans.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_ITEM_RE = re.compile(r"(?:[-*+]|[0-9]{1,9}[.)])(?: |$)")
_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.S)
# Link targets: inline links and images, reference definitions, autolinks,
# and the src/href attributes of HTML tags.
_LINK_TARGET_RES = (
    re.compile(r"\]\(\s*<?([^)\s>]*)"),
    re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?([^\s>]+)", re.M),
    re.compile(r"<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*)>"),
)
_HTML_TAG_RE = re.compile(r"<[A-Za-z][A-Za-z0-9-]*\s[^<>]*>")
_HTML_LINK_ATTR_RE = re.compile(
    r"""(?<![\w-])(?:src|href)\s*=\s*["']?([^"'\s>]+)""", re.I
)
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
#: link schemes that resolve wherever the installed file ends up
WEB_SCHEMES = ("http", "https", "mailto")


class SkillError(Exception):
    """Raised when a skill directory is malformed.

    For a malformed skill, ``rule`` names the rule it breaks (e.g.
    ``meta.version``; ``skilldeck validate`` lists them), ``file`` is the file
    that breaks it, ``line`` the 1-based line when known, and ``detail`` a
    one-line message without the leading skill directory. Other errors leave
    ``rule``, ``file`` and ``line`` None.
    """

    def __init__(
        self,
        message: str,
        *,
        rule: str | None = None,
        file: Path | None = None,
        detail: str | None = None,
        line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.rule = rule
        self.file = file
        self.detail = message if detail is None else detail
        self.line = line


def _invalid(
    skill_dir: Path, rule: str, detail: str, file: str = "meta.yaml"
) -> SkillError:
    """A :class:`SkillError` for ``skill_dir`` breaking ``rule``."""
    return SkillError(
        f"{skill_dir}: {detail}", rule=rule, file=skill_dir / file, detail=detail
    )


@dataclass(frozen=True)
class Deprecation:
    """Why a skill is deprecated, from which of its versions, and what replaces it."""

    since: str
    reason: str
    replacement: str | None = None


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    category: str
    version: str
    supported_agents: tuple[str, ...]
    body: str
    path: Path
    deprecated: Deprecation | None = None
    #: what the skill may ask an agent to do; the default requests nothing
    capabilities: Capabilities = Capabilities()


@dataclass(frozen=True)
class SkillMeta:
    """A skill's validated ``meta.yaml``."""

    name: str
    description: str
    category: str
    version: str
    supported_agents: tuple[str, ...]
    deprecated: Deprecation | None
    capabilities: Capabilities

    def skill(self, body: str, path: Path) -> Skill:
        """The skill these fields describe, with ``body`` as its ``skill.md``."""
        return Skill(
            name=self.name,
            description=self.description,
            category=self.category,
            version=self.version,
            supported_agents=self.supported_agents,
            body=body,
            path=path,
            deprecated=self.deprecated,
            capabilities=self.capabilities,
        )


def load_skill(skill_dir: Path, known_agents: Collection[str] | None = None) -> Skill:
    """Load and validate a single skill directory.

    If ``known_agents`` is given, every entry in ``supported-agents`` must be a
    member of it, so a typo'd agent name fails loudly instead of silently never
    matching an adapter.
    """
    meta_path = skill_dir / "meta.yaml"
    body_path = skill_dir / "skill.md"

    if is_link(skill_dir):
        raise SkillError(
            f"{skill_dir}: the skill directory is a {link_kind(skill_dir)}",
            rule="skill.link",
            file=skill_dir,
            detail=f"the skill directory is a {link_kind(skill_dir)}",
        )
    problems = bundle_problems(skill_dir) if skill_dir.is_dir() else []
    if problems:
        # several rules at once; validate reports each (see bundle_entries)
        raise SkillError(
            f"{skill_dir}: {'; '.join(problems)}. A skill directory holds only "
            "meta.yaml and skill.md, as regular files: skilldeck installs one "
            "file per skill, so a skill cannot ship (or declare) scripts, "
            "assets or links"
        )
    if not meta_path.is_file():
        raise _invalid(skill_dir, "meta.missing", "missing meta.yaml")
    if not body_path.is_file():
        raise _invalid(skill_dir, "body.missing", "missing skill.md", "skill.md")

    meta = _load_meta(skill_dir, known_agents)

    try:
        body = body_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid(
            skill_dir,
            "body.encoding",
            f"skill.md is not valid UTF-8: {exc}",
            "skill.md",
        ) from exc
    missing_assets = local_links(body)
    if missing_assets:
        raise _invalid(
            skill_dir,
            "references.local-link",
            f"skill.md links to {', '.join(missing_assets)}, which "
            "the skill cannot ship: a skill is only meta.yaml and skill.md, so "
            "a relative or file link has nothing to resolve to once installed. "
            f"Link to a web page ({', '.join(WEB_SCHEMES)}) or a #heading instead",
            "skill.md",
        )

    return meta.skill(body, skill_dir)


def check_meta(
    skill_dir: Path, known_agents: Collection[str] | None = None
) -> SkillMeta:
    """Validate ``skill_dir/meta.yaml`` alone, as :func:`load_skill` does.

    For ``skilldeck validate``, which checks the skill directory and
    ``skill.md`` separately. Raises :class:`SkillError` as :func:`load_skill`
    would.
    """
    if not (skill_dir / "meta.yaml").is_file():
        raise _invalid(skill_dir, "meta.missing", "missing meta.yaml")
    return _load_meta(skill_dir, known_agents)


def _load_meta(skill_dir: Path, known_agents: Collection[str] | None) -> SkillMeta:
    """Read and validate ``skill_dir/meta.yaml``, which exists."""
    meta_path = skill_dir / "meta.yaml"
    try:
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except UnicodeDecodeError as exc:
        raise _invalid(
            skill_dir, "meta.encoding", f"meta.yaml is not valid UTF-8: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise SkillError(
            f"{skill_dir}: meta.yaml is not valid YAML: {exc}",
            rule="meta.syntax",
            file=meta_path,
            detail=f"meta.yaml is not valid YAML: {_yaml_problem(exc)}",
            line=_yaml_line(exc),
        ) from exc
    if not isinstance(meta, dict):
        raise _invalid(skill_dir, "meta.syntax", "meta.yaml must be a YAML mapping")
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise _invalid(
            skill_dir,
            "meta.missing-field",
            f"meta.yaml missing fields: {', '.join(missing)}",
        )
    unknown = sorted(str(key) for key in meta if key not in ALLOWED_FIELDS)
    if unknown:
        raise _invalid(
            skill_dir,
            "meta.unknown-field",
            f"meta.yaml has unknown field(s): {', '.join(unknown)}; "
            f"the fields are {', '.join(ALLOWED_FIELDS)}",
        )

    name = _require_str(skill_dir, meta, "name")
    if len(name) > MAX_NAME_LENGTH or not NAME_RE.fullmatch(name):
        raise _invalid(
            skill_dir,
            "meta.name",
            f"meta.yaml name {name!r} must be at most "
            f"{MAX_NAME_LENGTH} lowercase letters, digits and single hyphens, "
            "starting and ending with a letter or digit",
        )
    if name != skill_dir.name:
        raise _invalid(
            skill_dir,
            "meta.name-mismatch",
            f"meta.yaml name '{name}' does not match directory name '{skill_dir.name}'",
        )

    description = _require_str(skill_dir, meta, "description")
    # Any line boundary ``str.splitlines`` knows, not just \n and \r: YAML
    # double-quoted escapes such as "\u2028" or "\x85" also break the one-line
    # ``skilldeck list`` output.
    if description.splitlines() != [description]:
        raise _invalid(
            skill_dir,
            "meta.description",
            "meta.yaml description must be a single line (a folded "
            "block needs >- rather than >, which keeps a final line break)",
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise _invalid(
            skill_dir,
            "meta.description",
            f"meta.yaml description is {len(description)} characters; "
            f"the limit is {MAX_DESCRIPTION_LENGTH}",
        )

    category = _require_str(skill_dir, meta, "category")

    raw_version = _require_version(skill_dir, meta["version"], "version")

    agents = meta["supported-agents"]
    if not isinstance(agents, list) or not agents:
        raise _invalid(
            skill_dir,
            "meta.supported-agents",
            "supported-agents must be a non-empty list",
        )
    if not all(isinstance(agent, str) for agent in agents):
        raise _invalid(
            skill_dir,
            "meta.supported-agents",
            "supported-agents entries must be strings",
        )
    duplicates = sorted({agent for agent in agents if agents.count(agent) > 1})
    if duplicates:
        raise _invalid(
            skill_dir,
            "meta.supported-agents",
            f"supported-agents lists agent(s) more than once: {', '.join(duplicates)}",
        )

    if known_agents is not None:
        unknown = [a for a in agents if a not in known_agents]
        if unknown:
            raise _invalid(
                skill_dir,
                "meta.unknown-agent",
                f"supported-agents has unknown agent(s): {', '.join(unknown)}",
            )

    deprecated = (
        _load_deprecation(skill_dir, meta["deprecated"], name, raw_version)
        if "deprecated" in meta
        else None
    )

    try:
        capabilities = parse_capabilities(meta["capabilities"])
    except CapabilityError as exc:
        raise _invalid(skill_dir, "meta.capabilities", f"meta.yaml {exc}") from exc

    return SkillMeta(
        name=name,
        description=description,
        category=category,
        version=raw_version,
        supported_agents=tuple(agents),
        deprecated=deprecated,
        capabilities=capabilities,
    )


def _yaml_problem(exc: yaml.YAMLError) -> str:
    """What is wrong with the YAML, on one line and without the source
    excerpt PyYAML quotes (which can echo a file's contents)."""
    if isinstance(exc, yaml.MarkedYAMLError) and exc.problem:
        if exc.context:
            return f"{exc.problem} ({exc.context})"
        return exc.problem
    return " ".join(str(exc).split())


def _yaml_line(exc: yaml.YAMLError) -> int | None:
    """The 1-based line PyYAML found the problem on, if it knows."""
    mark = getattr(exc, "problem_mark", None)
    return mark.line + 1 if mark is not None else None


def is_junk(name: str) -> bool:
    """Whether ``name`` is a file an OS or editor leaves behind, which loading
    a skill ignores (``provenance --verify`` does not)."""
    return name in _JUNK_NAMES or bool(_JUNK_RE.fullmatch(name))


def is_link(path: Path) -> bool:
    """Whether ``path`` is a symlink or, on Windows, a directory junction;
    neither is followed."""
    isjunction = getattr(os.path, "isjunction", None)  # Python 3.12+
    return path.is_symlink() or bool(isjunction and isjunction(path))


def link_kind(path: Path) -> str:
    return "symlink" if path.is_symlink() else "junction"


@dataclass(frozen=True)
class BundleEntry:
    """One entry of a skill directory that breaks the bundle rules."""

    #: the entry's file name; empty when the directory itself can't be listed
    name: str
    #: unreadable, link, directory, special, executable or extra
    kind: str
    message: str


def bundle_entries(skill_dir: Path) -> list[BundleEntry]:
    """What in ``skill_dir`` breaks the bundle rules; ``[]`` if nothing does.

    One entry per offending file: a symlink or junction (never followed), a
    directory or other non-regular file, or any file besides
    :data:`BUNDLE_FILES`, which is ``executable`` when its suffix, execute bit
    (not on Windows, which has none) or first bytes say it is a program.
    Every such file is refused, since a skill cannot ship or declare one. OS
    and editor leftovers (:func:`is_junk`) are skipped, unless one is a link:
    only an Emacs lock file (``.#name``) is a symlink by nature.
    """
    try:
        entries = sorted(skill_dir.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        return [
            BundleEntry("", "unreadable", f"cannot list the skill directory: {exc}")
        ]
    problems: list[BundleEntry] = []
    for entry in entries:
        name = entry.name
        try:
            mode = entry.lstat().st_mode
        except OSError as exc:
            problems.append(
                BundleEntry(name, "unreadable", f"cannot inspect {name}: {exc}")
            )
            continue
        link = stat.S_ISLNK(mode) or is_link(entry)
        if is_junk(name) and (not link or name.startswith(".#")):
            continue
        if link:
            problems.append(
                BundleEntry(name, "link", f"{name} is a {link_kind(entry)}")
            )
        elif stat.S_ISDIR(mode):
            problems.append(BundleEntry(name, "directory", f"{name} is a directory"))
        elif not stat.S_ISREG(mode):
            problems.append(
                BundleEntry(name, "special", f"{name} is not a regular file")
            )
        elif name not in BUNDLE_FILES:
            why = _executable(entry, mode)
            if why:
                problems.append(
                    BundleEntry(
                        name,
                        "executable",
                        f"{name} is an undeclared executable ({why})",
                    )
                )
            else:
                problems.append(
                    BundleEntry(name, "extra", f"{name} is not meta.yaml or skill.md")
                )
    return problems


def bundle_problems(skill_dir: Path) -> list[str]:
    """The message of each :func:`bundle_entries` entry; ``[]`` if none."""
    return [entry.message for entry in bundle_entries(skill_dir)]


def _executable(path: Path, mode: int) -> str | None:
    """Why the regular file at ``path`` is a program; None if nothing says so."""
    suffix = path.suffix.lower()
    if suffix in SCRIPT_SUFFIXES:
        return f"a {suffix} file"
    # Windows reports execute bits from the file's suffix, covered above
    if os.name != "nt" and mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        return "its execute bit is set"
    try:
        with path.open("rb") as handle:
            head = handle.read(4)
    except OSError:
        return None
    if head.startswith(b"#!"):
        return "it starts with #!"
    if head.startswith(_BINARY_MAGIC):
        return "a native binary"
    return None


def local_links(body: str) -> list[str]:
    """Link targets in ``body`` that name a file rather than a web page.

    Markdown links, images, reference definitions and autolinks, and the
    ``src`` and ``href`` attributes of HTML tags, outside code blocks (fenced
    or indented) and code spans. A target counts unless it is a ``#heading``
    anchor or uses one of :data:`WEB_SCHEMES` (or is scheme-relative,
    ``//host/...``); a relative path, an absolute one, a ``file:`` URL and any
    other scheme all count. Sorted, each once.
    """
    text = _CODE_SPAN_RE.sub("", "\n".join(_prose_lines(body)))
    targets = [
        target for pattern in _LINK_TARGET_RES for target in pattern.findall(text)
    ]
    for tag in _HTML_TAG_RE.findall(text):
        targets.extend(_HTML_LINK_ATTR_RE.findall(tag))
    found: set[str] = set()
    for target in targets:
        if not target or target.startswith(("#", "//")):
            continue
        scheme = _SCHEME_RE.match(target)
        if scheme and scheme.group(0)[:-1].lower() in WEB_SCHEMES:
            continue
        found.add(target)
    return sorted(found)


def _prose_lines(body: str) -> list[str]:
    """``body``'s lines outside fenced and indented code blocks.

    An indented code block is a run of lines indented four or more columns
    that starts after a blank line, outside a list: inside one, that
    indentation continues a list item. A list lasts until a line starts at
    column 0 after a blank line, or a heading.
    """
    prose: list[str] = []
    fence: str | None = None
    in_list = in_code = False
    after_blank = True
    for line in body.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence is not None:
            closer = fence_match.group(1) if fence_match else ""
            if closer[:1] == fence[0] and len(closer) >= len(fence):
                fence = None
            continue
        if fence_match:
            fence = fence_match.group(1)
            in_code = False
            continue
        expanded = line.expandtabs(4)
        content = expanded.lstrip(" ")
        indent = len(expanded) - len(content)
        if not content:
            after_blank = True
            prose.append("")
            continue
        if indent >= 4 and not in_list and (after_blank or in_code):
            in_code = True
            after_blank = False
            continue
        in_code = False
        if indent < 4 and _LIST_ITEM_RE.match(content):
            in_list = True
        elif indent == 0 and (after_blank or content.startswith("#")):
            in_list = False
        after_blank = False
        prose.append(line)
    return prose


def _require_str(skill_dir: Path, meta: dict[Any, Any], field: str) -> str:
    """Return ``meta[field]`` if it is a non-blank string, else fail loudly."""
    value = meta[field]
    if not isinstance(value, str) or not value.strip():
        raise _invalid(
            skill_dir, f"meta.{field}", f"meta.yaml {field} must be a non-empty string"
        )
    return value


def _require_version(skill_dir: Path, value: object, field: str) -> str:
    """Return ``value`` if it is a MAJOR.MINOR.PATCH string, else fail loudly."""
    rule = "meta.version" if field == "version" else "meta.deprecated"
    if not isinstance(value, str):
        # An unquoted ``version: 1.10`` is the float 1.1 by the time it gets
        # here; stringifying it would silently record the wrong version.
        raise _invalid(
            skill_dir,
            rule,
            f"meta.yaml {field} must be a string, but YAML read it "
            f"as {type(value).__name__} {value!r}; quote it, "
            f'e.g. {field.rpartition(".")[2]}: "1.10.0"',
        )
    if not VERSION_RE.fullmatch(value):
        raise _invalid(
            skill_dir,
            rule,
            f"meta.yaml {field} {value!r} must be MAJOR.MINOR.PATCH, e.g. 0.1.0",
        )
    return value


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _load_deprecation(
    skill_dir: Path, raw: object, name: str, version: str
) -> Deprecation:
    """Validate the optional ``deprecated`` mapping of skill ``name``.

    ``since`` is the skill's own version that first carried the deprecation,
    so it can be no later than ``version``. ``replacement``, when given, names
    another skill; :func:`discover_skills` checks that it exists.
    """
    shape = (
        "deprecated must be a mapping with since and reason (and optionally "
        "replacement); leave it out for a skill that is not deprecated"
    )
    if not isinstance(raw, dict):
        raise _invalid(skill_dir, "meta.deprecated", f"meta.yaml {shape}")
    unknown = sorted(str(key) for key in raw if key not in DEPRECATION_FIELDS)
    if unknown:
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            f"meta.yaml deprecated has unknown field(s): {', '.join(unknown)}; {shape}",
        )
    missing = [field for field in ("since", "reason") if field not in raw]
    if missing:
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            f"meta.yaml deprecated missing fields: {', '.join(missing)}",
        )

    since = _require_version(skill_dir, raw["since"], "deprecated.since")
    if _version_key(since) > _version_key(version):
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            f"meta.yaml deprecated.since {since!r} is later than "
            f"the skill's version {version!r}; since is the skill version that "
            "first carried the deprecation",
        )

    reason = raw["reason"]
    if isinstance(reason, str):
        # A folded ``reason: >`` block keeps one final line break. Dropping
        # trailing line breaks accepts it without changing any other value:
        # the single-line check below rejects every value that has one.
        reason = reason.rstrip("\r\n")
    if not isinstance(reason, str) or not reason.strip():
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            "meta.yaml deprecated.reason must be a non-empty string",
        )
    if reason.splitlines() != [reason] or len(reason) > MAX_DESCRIPTION_LENGTH:
        raise _invalid(
            skill_dir,
            "meta.deprecated",
            "meta.yaml deprecated.reason must be a single line of "
            f"at most {MAX_DESCRIPTION_LENGTH} characters",
        )

    replacement = raw.get("replacement")
    if replacement is not None:
        if not isinstance(replacement, str) or not NAME_RE.fullmatch(replacement):
            raise _invalid(
                skill_dir,
                "meta.deprecated",
                "meta.yaml deprecated.replacement must be a skill "
                f"name or null, not {replacement!r}",
            )
        if replacement == name:
            raise _invalid(
                skill_dir,
                "meta.deprecated",
                "meta.yaml deprecated.replacement names the skill itself",
            )
    return Deprecation(since=since, reason=reason, replacement=replacement)


def discover_skills(
    skills_dir: Path | None = None, known_agents: Collection[str] | None = None
) -> list[Skill]:
    """Load every skill under ``skills_dir`` (sorted by name)."""
    root = skills_dir or DEFAULT_SKILLS_DIR
    if not root.is_dir():
        raise SkillError(f"skills directory not found: {root}")

    skills = []
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or is_junk(child.name):
            continue
        # checked before is_dir(), which follows the link
        if is_link(child):
            raise SkillError(f"{child}: the skill directory is a {link_kind(child)}")
        if child.is_dir():
            skills.append(load_skill(child, known_agents))
    errors = replacement_errors(skills)
    if errors:
        raise errors[0]
    return skills


def replacement_errors(skills: list[Skill]) -> list[SkillError]:
    """One error per deprecated skill in ``skills`` whose replacement is not a
    current skill in ``skills`` that supports every agent the deprecated one
    does.

    A replacement that is missing, deprecated itself, or missing one of those
    agents would send users to a skill they cannot install or should not
    adopt.
    """
    by_name = {skill.name: skill for skill in skills}
    errors: list[SkillError] = []
    for skill in skills:
        if skill.deprecated is None or skill.deprecated.replacement is None:
            continue
        replacement = by_name.get(skill.deprecated.replacement)
        if replacement is None:
            detail = (
                "meta.yaml deprecated.replacement "
                f"{skill.deprecated.replacement!r} is not a skill in the same "
                "directory"
            )
        elif replacement.deprecated is not None:
            detail = (
                "meta.yaml deprecated.replacement "
                f"{replacement.name!r} is itself deprecated; name the skill "
                "that replaces it instead"
            )
        else:
            lacking = [
                agent
                for agent in skill.supported_agents
                if agent not in replacement.supported_agents
            ]
            if not lacking:
                continue
            detail = (
                "meta.yaml deprecated.replacement "
                f"{replacement.name!r} does not support {', '.join(lacking)}, "
                f"which {skill.name} supports; its users there would have no "
                "replacement to install"
            )
        errors.append(_invalid(skill.path, "meta.deprecated-replacement", detail))
    return errors
