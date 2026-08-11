#!/usr/bin/env python3
"""Stamp an exact release tag and commit into the package before building."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPOSITORY_URL = "https://github.com/IcebergAI/skilldeck"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def project_version(root: Path) -> str:
    match = _VERSION_RE.search((root / "pyproject.toml").read_text(encoding="utf-8"))
    if not match:
        raise ValueError("pyproject.toml has no project version")
    return match.group(1)


def expected_metadata(
    root: Path, source_ref: str, source_commit: str
) -> dict[str, object]:
    version = project_version(root)
    expected_ref = f"refs/tags/v{version}"
    if source_ref != expected_ref:
        raise ValueError(
            f"source ref {source_ref!r} does not match package tag {expected_ref!r}"
        )
    if not _COMMIT_RE.fullmatch(source_commit):
        raise ValueError("source commit must be 40 lowercase hexadecimal characters")
    return {
        "schema_version": 1,
        "source_commit": source_commit,
        "source_ref": source_ref,
        "source_repository": REPOSITORY_URL,
    }


def metadata_path(root: Path) -> Path:
    return root / "src" / "skilldeck" / "_build_metadata.json"


def serialized(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def stamp(
    root: Path,
    source_ref: str,
    source_commit: str,
    *,
    check: bool = False,
) -> None:
    expected = serialized(expected_metadata(root, source_ref, source_commit))
    path = metadata_path(root)
    if check:
        if path.read_text(encoding="utf-8") != expected:
            raise ValueError(f"{path} does not contain the expected release identity")
        return
    path.write_text(expected, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        stamp(
            args.root.resolve(),
            args.source_ref,
            args.source_commit,
            check=args.check,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
