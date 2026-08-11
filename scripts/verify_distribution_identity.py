#!/usr/bin/env python3
"""Verify wheel, sdist, and Claude plugin share one exact release identity."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skilldeck.adapters import ADAPTERS  # noqa: E402
from skilldeck.provenance import (  # noqa: E402
    REPOSITORY_URL,
    canonical_skill_digest,
    claude_plugin_metadata,
    sha256_text,
)
from skilldeck.registry import Skill  # noqa: E402

MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1_024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class VerificationError(ValueError):
    """A release artifact does not satisfy the identity contract."""


def _safe_member(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise VerificationError(f"unsafe archive member: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise VerificationError(f"unsafe archive member: {name!r}")
    return path


def read_zip(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise VerificationError("too many archive members")
        total = 0
        for member in members:
            name = str(_safe_member(member.filename))
            if name in seen:
                raise VerificationError(f"duplicate archive member: {name}")
            seen.add(name)
            if member.flag_bits & 0x1:
                raise VerificationError(f"encrypted archive member: {name}")
            mode = member.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if member.is_dir():
                continue
            if kind not in (0, stat.S_IFREG):
                raise VerificationError(f"non-regular archive member: {name}")
            if member.file_size > MAX_MEMBER_BYTES:
                raise VerificationError(f"oversized archive member: {name}")
            total += member.file_size
            if total > MAX_ARCHIVE_BYTES:
                raise VerificationError("archive exceeds aggregate size limit")
            payload = archive.read(member)
            if len(payload) != member.file_size:
                raise VerificationError(f"truncated archive member: {name}")
            files[name] = payload
    return files


def read_tar(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    with tarfile.open(path, mode="r|gz") as archive:
        total = 0
        count = 0
        for member in archive:
            count += 1
            if count > MAX_ARCHIVE_MEMBERS:
                raise VerificationError("too many archive members")
            name = str(_safe_member(member.name))
            if name in seen:
                raise VerificationError(f"duplicate archive member: {name}")
            seen.add(name)
            if member.isdir():
                continue
            if not member.isfile():
                raise VerificationError(f"non-regular archive member: {name}")
            if member.size > MAX_MEMBER_BYTES:
                raise VerificationError(f"oversized archive member: {name}")
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise VerificationError("archive exceeds aggregate size limit")
            stream = archive.extractfile(member)
            if stream is None:
                raise VerificationError(f"unreadable archive member: {name}")
            payload = stream.read(MAX_MEMBER_BYTES + 1)
            if len(payload) != member.size:
                raise VerificationError(f"truncated archive member: {name}")
            files[name] = payload
    return files


def _one_suffix(files: dict[str, bytes], suffix: str) -> tuple[str, bytes]:
    found = [(name, data) for name, data in files.items() if name.endswith(suffix)]
    if len(found) != 1:
        raise VerificationError(f"expected exactly one {suffix}, found {len(found)}")
    return found[0]


def _json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON in {label}") from exc
    if not isinstance(data, dict):
        raise VerificationError(f"{label} must be a JSON object")
    return data


def _validate_build(
    data: dict[str, Any], version: str, source_ref: str, source_commit: str
) -> None:
    expected = {
        "schema_version": 1,
        "source_commit": source_commit,
        "source_ref": source_ref,
        "source_repository": REPOSITORY_URL,
    }
    if data != expected:
        raise VerificationError("distribution build metadata does not match release")
    if source_ref != f"refs/tags/v{version}" or not _COMMIT_RE.fullmatch(source_commit):
        raise VerificationError("invalid expected release identity")


def _validate_manifest_shape(
    data: dict[str, Any], version: str
) -> list[dict[str, Any]]:
    if set(data) != {"schema_version", "package_version", "skills"}:
        raise VerificationError("content manifest has unknown or missing fields")
    if data["schema_version"] != 1 or data["package_version"] != version:
        raise VerificationError("content manifest version mismatch")
    records = data["skills"]
    if not isinstance(records, list) or not records:
        raise VerificationError("content manifest has no skills")
    expected_fields = {
        "name",
        "version",
        "canonical_sha256",
        "meta_sha256",
        "body_sha256",
        "claude_rendered_sha256",
    }
    names: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != expected_fields:
            raise VerificationError("invalid skill record in content manifest")
        if not isinstance(record["name"], str) or not isinstance(
            record["version"], str
        ):
            raise VerificationError("invalid skill identity in content manifest")
        for field in (
            "canonical_sha256",
            "meta_sha256",
            "body_sha256",
            "claude_rendered_sha256",
        ):
            if not isinstance(record[field], str) or not _DIGEST_RE.fullmatch(
                record[field]
            ):
                raise VerificationError(f"invalid {field} in content manifest")
        names.append(record["name"])
    if names != sorted(names) or len(names) != len(set(names)):
        raise VerificationError("content manifest skills are unsorted or duplicated")
    return records


def _distribution_skills(
    files: dict[str, bytes], marker: str
) -> dict[str, dict[str, str]]:
    pattern = re.compile(
        rf"(?:^|/){re.escape(marker)}/skills/([^/]+)/(meta\.yaml|skill\.md)$"
    )
    skills: dict[str, dict[str, str]] = {}
    for name, payload in files.items():
        match = pattern.search(name)
        if not match:
            continue
        skill_name, filename = match.groups()
        record = skills.setdefault(skill_name, {})
        if filename in record:
            raise VerificationError(f"duplicate {filename} for {skill_name}")
        try:
            record[filename] = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VerificationError(f"non-UTF-8 canonical skill: {skill_name}") from exc
    return skills


def validate_distribution(
    files: dict[str, bytes],
    *,
    marker: str,
    version: str,
    source_ref: str,
    source_commit: str,
) -> dict[str, Any]:
    _, manifest_bytes = _one_suffix(files, f"{marker}/_content_manifest.json")
    _, build_bytes = _one_suffix(files, f"{marker}/_build_metadata.json")
    manifest = _json_bytes(manifest_bytes, "content manifest")
    build = _json_bytes(build_bytes, "build metadata")
    records = _validate_manifest_shape(manifest, version)
    _validate_build(build, version, source_ref, source_commit)

    skills = _distribution_skills(files, marker)
    expected_names = {record["name"] for record in records}
    if set(skills) != expected_names:
        raise VerificationError(
            "distribution skill set does not match content manifest"
        )
    for record in records:
        name = record["name"]
        source = skills[name]
        if set(source) != {"meta.yaml", "skill.md"}:
            raise VerificationError(f"incomplete canonical skill: {name}")
        meta_text = source["meta.yaml"]
        body_text = source["skill.md"]
        actual = {
            "canonical_sha256": canonical_skill_digest(meta_text, body_text),
            "meta_sha256": sha256_text(meta_text),
            "body_sha256": sha256_text(body_text),
        }
        for field, digest in actual.items():
            if record[field] != digest:
                raise VerificationError(f"{name} {field} does not match manifest")
    return manifest


def validate_plugin(
    plugin_dir: Path,
    manifest: dict[str, Any],
    canonical_skills: dict[str, dict[str, str]],
    version: str,
) -> None:
    manifest_path = plugin_dir / ".skilldeck" / "content-manifest.json"
    plugin_json_path = plugin_dir / ".claude-plugin" / "plugin.json"
    for path in (manifest_path, plugin_json_path):
        if path.is_symlink() or not path.is_file():
            raise VerificationError(f"missing or unsafe plugin file: {path}")
    plugin_manifest = _json_bytes(manifest_path.read_bytes(), "plugin manifest")
    if plugin_manifest != manifest:
        raise VerificationError("plugin and Python content manifests differ")
    plugin_json = _json_bytes(plugin_json_path.read_bytes(), "plugin.json")

    records = _validate_manifest_shape(plugin_manifest, version)
    expected = {record["name"] for record in records}
    skills_root = plugin_dir / "skills"
    expected_paths = {
        ".claude-plugin/plugin.json",
        ".skilldeck/content-manifest.json",
        *(f"skills/{name}/SKILL.md" for name in expected),
    }
    actual_paths = {
        path.relative_to(plugin_dir).as_posix()
        for path in plugin_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_paths != expected_paths:
        raise VerificationError("plugin file set does not match generated contract")
    if any(
        path.is_symlink() or not (path.is_file() or path.is_dir())
        for path in plugin_dir.rglob("*")
    ):
        raise VerificationError("plugin contains unsafe filesystem entry")
    actual = {path.parent.name for path in skills_root.glob("*/SKILL.md")}
    if actual != expected:
        raise VerificationError("plugin skill set does not match content manifest")
    derived: list[Skill] = []
    for record in records:
        path = skills_root / record["name"] / "SKILL.md"
        if path.is_symlink() or not path.is_file():
            raise VerificationError(f"missing or unsafe plugin skill: {record['name']}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise VerificationError(
                f"non-UTF-8 plugin skill: {record['name']}"
            ) from exc
        if sha256_text(text) != record["claude_rendered_sha256"]:
            raise VerificationError(
                f"plugin rendering does not match manifest: {record['name']}"
            )
        source = canonical_skills.get(record["name"])
        if source is None or set(source) != {"meta.yaml", "skill.md"}:
            raise VerificationError(f"canonical skill unavailable: {record['name']}")
        try:
            meta = yaml.safe_load(source["meta.yaml"])
        except yaml.YAMLError as exc:
            raise VerificationError(
                f"invalid canonical metadata: {record['name']}"
            ) from exc
        agents = meta.get("supported-agents") if isinstance(meta, dict) else None
        if (
            not isinstance(meta, dict)
            or meta.get("name") != record["name"]
            or not isinstance(agents, list)
            or not all(isinstance(agent, str) for agent in agents)
        ):
            raise VerificationError(f"invalid canonical metadata: {record['name']}")
        skill = Skill(
            name=record["name"],
            description=str(meta.get("description")),
            category=str(meta.get("category")),
            version=record["version"],
            supported_agents=tuple(agents),
            body=source["skill.md"],
            path=Path(record["name"]),
        )
        rendered_digest = sha256_text(ADAPTERS["claude"].render(skill))
        if rendered_digest != record["claude_rendered_sha256"]:
            raise VerificationError(
                "plugin rendering is not derived from canonical skill: "
                f"{record['name']}"
            )
        derived.append(skill)
    if plugin_json != claude_plugin_metadata(version, derived):
        raise VerificationError("plugin metadata does not match generated contract")


def verify(
    wheel: Path,
    sdist: Path,
    plugin_dir: Path,
    version: str,
    source_ref: str,
    source_commit: str,
) -> None:
    wheel_files = read_zip(wheel)
    wheel_manifest = validate_distribution(
        wheel_files,
        marker="skilldeck",
        version=version,
        source_ref=source_ref,
        source_commit=source_commit,
    )
    sdist_manifest = validate_distribution(
        read_tar(sdist),
        marker="src/skilldeck",
        version=version,
        source_ref=source_ref,
        source_commit=source_commit,
    )
    if wheel_manifest != sdist_manifest:
        raise VerificationError("wheel and sdist content manifests differ")
    validate_plugin(
        plugin_dir,
        wheel_manifest,
        _distribution_skills(wheel_files, "skilldeck"),
        version,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-ref", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    try:
        verify(
            args.wheel,
            args.sdist,
            args.plugin_dir,
            args.expected_version,
            args.expected_ref,
            args.expected_commit,
        )
    except (OSError, VerificationError, tarfile.TarError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(
        f"ok: wheel, sdist, and plugin match {args.expected_ref} "
        f"at {args.expected_commit}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
