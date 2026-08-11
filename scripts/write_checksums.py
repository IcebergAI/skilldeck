#!/usr/bin/env python3
"""Write or verify the exact standard checksum set for release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
from pathlib import Path

CHECKSUMS_NAME = "SHA256SUMS"
_LINE_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)$")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="release directory or SHA256SUMS file")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            verify(args.path)
            print(f"ok: verified exact release checksum set in {args.path.parent}")
        else:
            output = write(args.path)
            print(f"wrote {output}")
    except (OSError, ChecksumError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
