"""Install stamps.

Every file skilldeck installs ends with a one-line HTML comment recording the
skill name, the skill version, and a hash of the content above it:

    <!-- skilldeck name=security-review version=0.3.0 hash=<sha256> -->

``status``/``update`` compare the stamp against the bundled skill to detect
stale installs; ``install`` compares the hash to detect local edits so it never
silently clobbers them. Markdown renderers and agents ignore the comment.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_STAMP_RE = re.compile(
    r"<!-- skilldeck name=(?P<name>\S+) version=(?P<version>\S+) "
    r"hash=(?P<hash>[0-9a-f]{64}) -->\n?"
)


@dataclass(frozen=True)
class Stamp:
    name: str
    version: str
    #: True if the content no longer matches the hash recorded at install time
    modified: bool


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def stamp(content: str, name: str, version: str) -> str:
    """Append a stamp comment to ``content`` (newline-terminating it first)."""
    if not content.endswith("\n"):
        content += "\n"
    digest = _digest(content)
    return f"{content}<!-- skilldeck name={name} version={version} hash={digest} -->\n"


def parse(text: str) -> Stamp | None:
    """Read the stamp off an installed file's ``text``; None if it has none.

    The stamp is written as the last line; if anything was appended after it,
    or the content above it no longer matches its hash, the file counts as
    modified. When the text somehow contains several stamp-shaped lines, the
    last one is the stamp.
    """
    match: re.Match[str] | None = None
    for candidate in _STAMP_RE.finditer(text):
        match = candidate
    if match is None:
        return None
    content = text[: match.start()]
    modified = match.end() != len(text) or _digest(content) != match.group("hash")
    return Stamp(
        name=match.group("name"),
        version=match.group("version"),
        modified=modified,
    )
