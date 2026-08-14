#!/usr/bin/env python3
"""Validate that a release SPDX SBOM covers runtime, not development, packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MAX_SBOM_BYTES = 16 * 1024 * 1024
REQUIRED_PACKAGES = {"skilldeck", "click", "pyyaml"}
FORBIDDEN_PACKAGES = {"pytest", "ruff", "mypy"}


class SbomError(ValueError):
    """The generated SBOM does not describe the release runtime."""


def verify(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SbomError(f"SBOM is not a regular file: {path}")
    if path.stat().st_size > MAX_SBOM_BYTES:
        raise SbomError("SBOM exceeds GitHub attestation size limit")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SbomError("SBOM is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or data.get("spdxVersion") != "SPDX-2.3":
        raise SbomError("SBOM must use SPDX-2.3")
    packages = data.get("packages")
    if not isinstance(packages, list):
        raise SbomError("SBOM has no package list")
    names: set[str] = set()
    identifiers: set[str] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise SbomError("SBOM package entry is not an object")
        name = package.get("name")
        identifier = package.get("SPDXID")
        if not isinstance(name, str) or not isinstance(identifier, str):
            raise SbomError("SBOM package is missing name or SPDXID")
        if identifier in identifiers:
            raise SbomError(f"duplicate SBOM package identifier: {identifier}")
        names.add(name.casefold())
        identifiers.add(identifier)
    missing = sorted(REQUIRED_PACKAGES - names)
    if missing:
        raise SbomError(f"SBOM is missing runtime package(s): {', '.join(missing)}")
    forbidden = sorted(FORBIDDEN_PACKAGES & names)
    if forbidden:
        raise SbomError(f"SBOM contains development package(s): {', '.join(forbidden)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbom", type=Path)
    args = parser.parse_args()
    try:
        verify(args.sbom)
    except (OSError, SbomError) as exc:
        parser.error(str(exc))
    print(f"ok: {args.sbom} is an SPDX-2.3 runtime SBOM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
