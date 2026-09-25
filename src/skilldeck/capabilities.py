"""Skill capability declarations.

Every skill's ``meta.yaml`` carries a ``capabilities`` block saying what the
skill may ask an agent to do beyond following its text: the files it reads and
edits, the commands it may run, what it contacts over the network and why, the
credentials it handles, the agent tools it needs beyond reading files and
running those commands, and the files it may create. ``schema`` versions the
block's format; this module reads schema 1.

A declaration is for review, not enforcement. Skilldeck cannot sandbox the
agents it installs into, and no metadata makes a malicious instruction safe.
Anything a skill does not declare, it does not request: an attempt to do it
comes from somewhere other than the skill, to refuse or review by hand.
``docs/authoring-skills.md`` documents the format.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

#: the capability schema version this module reads and writes
CAPABILITY_SCHEMA = 1

#: every key of the ``capabilities`` block, all required
FIELDS = ("schema", "files", "commands", "network", "credentials", "tools", "artifacts")
FILE_FIELDS = ("read", "write")
#: how much of the project the skill reads: nothing, the changed files, or any
#: file in the repository
READ_SCOPES = ("none", "diff", "repo")
#: whether it edits files already in the project
WRITE_SCOPES = ("none", "repo")
#: the list fields, in the order summaries show them
LIST_FIELDS = ("commands", "network", "credentials", "tools", "artifacts")
MAX_ENTRY_LENGTH = 200

# A command names a program on PATH (never a path to a file: a skill ships no
# scripts) followed by its subcommand or arguments, single-spaced. A
# placeholder in angle brackets stands for a command the project defines.
_PROGRAM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_PLACEHOLDER_RE = re.compile(r"<[^<>`]+>")
# A declared command is one simple command: a pipeline, a redirection or a
# substitution would hide what actually runs.
_SHELL_CHARS = frozenset(";|&$<>()`")
# One component of a declared path: no separators, and not "." or "..".
_SEGMENT_RE = re.compile(r"[A-Za-z0-9._-]+")
_DRIVE_RE = re.compile(r"[A-Za-z]:")

_SHAPE = (
    "capabilities must be a mapping of schema (1), files (read, write), "
    "commands, network, credentials, tools and artifacts; see "
    "docs/authoring-skills.md"
)
_READ_TEXT = {
    "none": "reads no files",
    "diff": "reads the changed files",
    "repo": "reads the repository",
}
_WRITE_TEXT = {
    "none": "edits no files",
    "repo": "may edit files in the repository",
}
# (label, field) of each list the notice shows, in order; commands and paths
# are shown as code
_NOTICE_LABELS = (
    ("Commands", "commands"),
    ("Network", "network"),
    ("Credentials", "credentials"),
    ("Agent tools", "tools"),
    ("Creates", "artifacts"),
)
_CODE_FIELDS = frozenset({"commands", "artifacts"})


class CapabilityError(ValueError):
    """A ``capabilities`` block that breaks the schema."""


class FileCapabilities(TypedDict):
    read: str
    write: str


class CapabilityRecord(TypedDict):
    """A declaration as plain data, for the catalog."""

    schema: int
    files: FileCapabilities
    commands: list[str]
    network: list[str]
    credentials: list[str]
    tools: list[str]
    artifacts: list[str]


@dataclass(frozen=True)
class Capabilities:
    """What a skill may ask an agent to do; the default requests nothing."""

    read: str = "none"
    write: str = "none"
    #: commands it may ask the agent to run, e.g. ``git diff``
    commands: tuple[str, ...] = ()
    #: what it may contact, and why
    network: tuple[str, ...] = ()
    #: secrets it asks the agent to read, pass on or send
    credentials: tuple[str, ...] = ()
    #: agent tools it needs beyond reading files and running ``commands``
    tools: tuple[str, ...] = ()
    #: project-relative paths of files it may create
    artifacts: tuple[str, ...] = ()

    @property
    def beyond_reading(self) -> bool:
        """Whether it asks for anything but reading files."""
        return self.write != "none" or any(
            getattr(self, field) for field in LIST_FIELDS
        )

    def record(self) -> CapabilityRecord:
        return {
            "schema": CAPABILITY_SCHEMA,
            "files": {"read": self.read, "write": self.write},
            "commands": list(self.commands),
            "network": list(self.network),
            "credentials": list(self.credentials),
            "tools": list(self.tools),
            "artifacts": list(self.artifacts),
        }


def parse_capabilities(raw: object) -> Capabilities:
    """Validate a decoded ``capabilities`` block; raise :class:`CapabilityError`.

    Every key is required, so each skill states each capability, if only as
    ``[]`` or ``none``; an unknown key is an error rather than ignored.
    """
    if not isinstance(raw, dict):
        raise CapabilityError(_SHAPE)
    _exact_keys(raw, FIELDS, "capabilities")
    schema = raw["schema"]
    if type(schema) is not int or schema != CAPABILITY_SCHEMA:
        raise CapabilityError(
            f"capabilities.schema must be {CAPABILITY_SCHEMA}, the capability "
            f"schema this skilldeck reads, not {schema!r}"
        )
    files = raw["files"]
    if not isinstance(files, dict):
        raise CapabilityError(
            "capabilities.files must be a mapping with read "
            f"({' | '.join(READ_SCOPES)}) and write ({' | '.join(WRITE_SCOPES)})"
        )
    _exact_keys(files, FILE_FIELDS, "capabilities.files")
    read = _choice(files["read"], READ_SCOPES, "capabilities.files.read")
    write = _choice(files["write"], WRITE_SCOPES, "capabilities.files.write")
    return Capabilities(
        read=read,
        write=write,
        commands=_entries(raw, "commands", _check_command),
        network=_entries(raw, "network", _check_text),
        credentials=_entries(raw, "credentials", _check_text),
        tools=_entries(raw, "tools", _check_text),
        artifacts=_entries(raw, "artifacts", _check_path),
    )


def _exact_keys(raw: dict[object, object], fields: tuple[str, ...], where: str) -> None:
    unknown = sorted(str(key) for key in raw if key not in fields)
    if unknown:
        raise CapabilityError(
            f"{where} has unknown field(s): {', '.join(unknown)}; "
            f"the fields are {', '.join(fields)}"
        )
    missing = [field for field in fields if field not in raw]
    if missing:
        raise CapabilityError(
            f"{where} missing field(s): {', '.join(missing)}; declare each "
            "one, as [] or none when the skill does not need it"
        )


def _choice(value: object, choices: tuple[str, ...], where: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise CapabilityError(
            f"{where} must be one of {', '.join(choices)}, not {value!r}"
        )
    return value


def _entries(
    raw: dict[object, object], field: str, check: Callable[[str, str], None]
) -> tuple[str, ...]:
    where = f"capabilities.{field}"
    value = raw[field]
    if not isinstance(value, list):
        raise CapabilityError(
            f"{where} must be a list ([] when the skill needs none), not {value!r}"
        )
    for entry in value:
        if not isinstance(entry, str):
            raise CapabilityError(f"{where} entries must be strings, not {entry!r}")
        check(entry, where)
    duplicates = sorted({entry for entry in value if value.count(entry) > 1})
    if duplicates:
        raise CapabilityError(
            f"{where} lists entries more than once: {', '.join(duplicates)}"
        )
    return tuple(value)


def _check_text(entry: str, where: str) -> None:
    """A short, single line of printable text with no outer whitespace."""
    if not entry.strip():
        raise CapabilityError(f"{where} entries must not be empty")
    if (
        entry != entry.strip()
        or entry.splitlines() != [entry]
        or not entry.isprintable()
    ):
        raise CapabilityError(
            f"{where} entry {entry!r} must be one line of printable text "
            "without leading or trailing spaces"
        )
    if len(entry) > MAX_ENTRY_LENGTH:
        raise CapabilityError(
            f"{where} entry is {len(entry)} characters; the limit is {MAX_ENTRY_LENGTH}"
        )


def _check_command(entry: str, where: str) -> None:
    _check_text(entry, where)
    if _PLACEHOLDER_RE.fullmatch(entry):
        return
    program = entry.split(" ", 1)[0]
    if " ".join(entry.split()) != entry or _SHELL_CHARS.intersection(entry):
        raise CapabilityError(
            f"{where} entry {entry!r} must be one command such as `git diff`, "
            "single-spaced, without shell operators, redirections or "
            "substitutions (; | & $ < > ( ) and backticks)"
        )
    if "/" in program or "\\" in program:
        raise CapabilityError(
            f"{where} entry {entry!r} runs a file by its path; a command must "
            "name a program on PATH, since a skill ships no scripts"
        )
    if not _PROGRAM_RE.fullmatch(program):
        raise CapabilityError(
            f"{where} entry {entry!r} must start with a program name "
            "(letters, digits, '.', '_', '+' and '-'), or be a <placeholder> "
            "for a command the project defines"
        )


def _check_path(entry: str, where: str) -> None:
    """A relative POSIX path that stays inside the project."""
    _check_text(entry, where)
    reason = None
    if "\\" in entry:
        reason = "use / as the separator, not \\"
    elif entry.startswith("/"):
        reason = "it is absolute"
    elif _DRIVE_RE.match(entry):
        reason = "it names a drive"
    elif entry.startswith("~"):
        reason = "it names a home directory"
    else:
        segments = entry.split("/")
        if any(segment in ("", ".", "..") for segment in segments):
            reason = "it has an empty, '.' or '..' component"
        elif not all(_SEGMENT_RE.fullmatch(segment) for segment in segments):
            reason = "use only letters, digits, '.', '_', '-' and '/'"
    if reason:
        raise CapabilityError(
            f"{where} entry {entry!r} must be a relative path inside the "
            f"project: {reason}"
        )


def files_text(capabilities: Capabilities) -> str:
    """The ``files`` declaration in words."""
    return f"{_READ_TEXT[capabilities.read]}; {_WRITE_TEXT[capabilities.write]}"


def summary(capabilities: Capabilities) -> list[tuple[str, tuple[str, ...]]]:
    """``(label, lines)`` for each capability, for a human-readable summary.

    Commands and paths share one line, comma-separated; each description gets
    a line of its own. A capability the skill does not request reads "none".
    """
    rows: list[tuple[str, tuple[str, ...]]] = [("files", (files_text(capabilities),))]
    for field in LIST_FIELDS:
        entries: tuple[str, ...] = getattr(capabilities, field)
        if not entries:
            rows.append((field, ("none",)))
        elif field in _CODE_FIELDS:
            rows.append((field, (", ".join(entries),)))
        else:
            rows.append((field, entries))
    return rows


def notice(capabilities: Capabilities) -> str:
    """The Markdown section adapters append to a skill that asks for more
    than reading files; empty for one that doesn't.

    It travels with the installed file, so whoever reads it (the agent, or a
    person reviewing what was installed) sees the declaration. Commands and
    paths are code, listed inline; descriptions get an item each once there
    are several.
    """
    if not capabilities.beyond_reading:
        return ""
    lines = [
        "## Declared capabilities",
        "",
        "What this skill may ask for, as declared in its skilldeck metadata",
        f"(capability schema {CAPABILITY_SCHEMA}). The declaration is for "
        "review: nothing enforces it.",
        "Anything not listed here is not requested by this skill.",
        "",
        f"- Files: {files_text(capabilities)}",
    ]
    for label, field in _NOTICE_LABELS:
        entries: tuple[str, ...] = getattr(capabilities, field)
        if not entries:
            continue
        if field in _CODE_FIELDS:
            lines.append(f"- {label}: " + ", ".join(f"`{e}`" for e in entries))
        elif len(entries) == 1:
            lines.append(f"- {label}: {entries[0]}")
        else:
            lines.append(f"- {label}:")
            lines.extend(f"  - {entry}" for entry in entries)
    return "\n".join(lines) + "\n"


def with_notice(body: str, capabilities: Capabilities) -> str:
    """``body`` as adapters render it: followed by :func:`notice`, if any."""
    text = notice(capabilities)
    if not text:
        return body
    if not body.endswith("\n"):
        body += "\n"
    return f"{body}\n{text}"
