#!/usr/bin/env python3
"""Write or verify the exact standard checksum set for release artifacts.

``SHA256SUMS`` travels in the same bundle as the files it covers, so it cannot
protect the bundle between release jobs. For that handoff the build job prints
the bundle's digests with ``--digests`` into a job output, which GitHub carries
separately from the artifact, and every later job checks the bundle it
downloaded against that output with ``--expect`` before using it.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

CHECKSUMS_NAME = "SHA256SUMS"
_NAME = r"[A-Za-z0-9][A-Za-z0-9._+-]*"
_LINE_RE = re.compile(rf"^([0-9a-f]{{64}})  ({_NAME})$")
_NAME_RE = re.compile(rf"^{_NAME}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ChecksumError(ValueError):
    """The release checksum set is unsafe or incomplete."""


def _exact_one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise ChecksumError(f"expected exactly one {label}, found {len(paths)}")
    return paths[0]


def release_assets(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise ChecksumError(f"release directory not found: {directory}")
    wheel = _exact_one(sorted(directory.glob("*.whl")), "wheel")
    sdist = _exact_one(sorted(directory.glob("*.tar.gz")), "source distribution")
    sbom = _exact_one(sorted(directory.glob("*.spdx.json")), "SPDX SBOM")
    expected = sorted((wheel, sdist, sbom), key=lambda path: path.name)
    allowed = {path.name for path in expected} | {CHECKSUMS_NAME}
    extras = sorted(
        path.name for path in directory.iterdir() if path.name not in allowed
    )
    if extras:
        raise ChecksumError(f"unexpected release artifact(s): {', '.join(extras)}")
    for path in expected:
        if path.is_symlink() or not path.is_file():
            raise ChecksumError(f"release artifact is not a regular file: {path.name}")
    return expected


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write(directory: Path) -> Path:
    assets = release_assets(directory)
    output = directory / CHECKSUMS_NAME
    if output.is_symlink():
        raise ChecksumError(f"refusing to replace symlink: {output}")
    text = "".join(f"{sha256_file(path)}  {path.name}\n" for path in assets)
    temporary = directory / f".{CHECKSUMS_NAME}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise ChecksumError(f"temporary checksum path already exists: {temporary}")
    try:
        temporary.write_text(text, encoding="ascii")
        os.replace(temporary, output)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
    return output


def verify(checksums: Path) -> None:
    if checksums.is_symlink() or not checksums.is_file():
        raise ChecksumError(f"checksum file is not a regular file: {checksums}")
    directory = checksums.parent
    expected = {path.name: path for path in release_assets(directory)}
    try:
        lines = checksums.read_text(encoding="ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ChecksumError("checksum file must be ASCII") from exc
    found: dict[str, str] = {}
    for line in lines:
        match = _LINE_RE.fullmatch(line)
        if not match:
            raise ChecksumError(f"malformed checksum line: {line!r}")
        digest, name = match.groups()
        if name in found:
            raise ChecksumError(f"duplicate checksum entry: {name}")
        found[name] = digest
    if set(found) != set(expected):
        raise ChecksumError(
            "checksum entries do not match the exact release artifact set"
        )
    for name, expected_digest in found.items():
        actual = sha256_file(expected[name])
        if not hmac.compare_digest(actual, expected_digest):
            raise ChecksumError(f"checksum mismatch: {name}")


def bundle_digests(directory: Path) -> dict[str, str]:
    """SHA-256 of every file in a verified release bundle, SHA256SUMS included."""
    checksums = directory / CHECKSUMS_NAME
    verify(checksums)
    files = [*release_assets(directory), checksums]
    return {path.name: sha256_file(path) for path in sorted(files)}


def parse_digests(text: str) -> dict[str, str]:
    """Decode the JSON object ``--digests`` printed: file name to hex SHA-256."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ChecksumError("expected digests are not valid JSON") from exc
    if (
        not isinstance(data, dict)
        or not data
        or not all(
            isinstance(name, str)
            and _NAME_RE.fullmatch(name)
            and isinstance(digest, str)
            and _DIGEST_RE.fullmatch(digest)
            for name, digest in data.items()
        )
    ):
        raise ChecksumError("expected digests must map file names to hex SHA-256")
    return data


def verify_digests(directory: Path, expected: Mapping[str, str]) -> None:
    """Require ``directory`` to hold exactly ``expected``, byte for byte."""
    if not directory.is_dir():
        raise ChecksumError(f"release directory not found: {directory}")
    present = {path.name: path for path in directory.iterdir()}
    if set(present) != set(expected):
        missing = sorted(set(expected) - set(present))
        extra = sorted(set(present) - set(expected))
        raise ChecksumError(
            f"bundle does not match the build job's file set "
            f"(missing: {', '.join(missing) or 'none'}; "
            f"unexpected: {', '.join(extra) or 'none'})"
        )
    for name, digest in sorted(expected.items()):
        path = present[name]
        if path.is_symlink() or not path.is_file():
            raise ChecksumError(f"release artifact is not a regular file: {name}")
        if not hmac.compare_digest(sha256_file(path), digest):
            raise ChecksumError(f"digest differs from the build job's: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="release directory or SHA256SUMS file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument(
        "--digests",
        action="store_true",
        help="print the verified bundle's digests as one line of JSON",
    )
    mode.add_argument(
        "--expect",
        metavar="JSON",
        help="require the directory to hold exactly these --digests",
    )
    args = parser.parse_args()
    try:
        if args.verify:
            verify(args.path)
            print(f"ok: verified exact release checksum set in {args.path.parent}")
        elif args.digests:
            digests = bundle_digests(args.path)
            print(json.dumps(digests, sort_keys=True, separators=(",", ":")))
        elif args.expect is not None:
            verify_digests(args.path, parse_digests(args.expect))
            print(f"ok: {args.path} matches the build job's digests")
        else:
            output = write(args.path)
            print(f"wrote {output}")
    except (OSError, ChecksumError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
