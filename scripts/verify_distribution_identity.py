#!/usr/bin/env python3
"""Verify wheel, sdist, and Claude plugin share one exact release identity.

Everything is compared with the files committed at ``HEAD`` of the source
checkout (read with ``git archive``, so a build step that edited the working
tree cannot vouch for itself):

* the sdist holds exactly the committed files plus ``PKG-INFO``, byte for byte;
* the wheel holds exactly the committed ``src/skilldeck`` files, byte for byte,
  plus ``METADATA``, ``WHEEL``, ``entry_points.txt``, ``RECORD`` and the
  license, with every file correctly hashed in ``RECORD`` and the metadata
  matching the committed ``pyproject.toml`` -- so an extra module, a ``.pth``
  file, changed code, or an added dependency fails;
* both carry the same content manifest and stamped build identity, and every
  bundled skill hashes to its manifest record;
* the committed Claude plugin renders from those skills and carries the
  version its release record dictates (``--release-plugin``: exactly the
  release version).

Only the stamped ``_build_metadata.json`` may differ from the commit, and it
must name exactly the expected tag and commit.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import email.message
import email.parser
import hashlib
import hmac
import io
import json
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import IO, Any, NamedTuple

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10: the committed pyproject.toml cannot be parsed
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skilldeck.adapters import ADAPTERS  # noqa: E402
from skilldeck.provenance import (  # noqa: E402
    REPOSITORY_URL,
    canonical_skill_digest,
    claude_plugin_content_digest,
    claude_plugin_metadata,
    claude_plugin_version,
    parse_plugin_release,
    sha256_text,
)
from skilldeck.registry import Skill  # noqa: E402

MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1_024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
PACKAGE = "skilldeck"
PACKAGE_SOURCE = f"src/{PACKAGE}/"
# stamped at build time, so the one package file that differs from the commit
BUILD_METADATA = "_build_metadata.json"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_EXTRA_MARKER_RE = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")
_NAME_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(.*)$", re.S)


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
    with path.open("rb") as stream:
        return _read_tar_stream(stream, "r|gz")


def _read_tar_stream(stream: IO[bytes], mode: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    with tarfile.open(fileobj=stream, mode=mode) as archive:
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
            content = archive.extractfile(member)
            if content is None:
                raise VerificationError(f"unreadable archive member: {name}")
            payload = content.read(MAX_MEMBER_BYTES + 1)
            if len(payload) != member.size:
                raise VerificationError(f"truncated archive member: {name}")
            files[name] = payload
    return files


def read_committed_tree(source_dir: Path) -> dict[str, bytes]:
    """Return every file committed at ``HEAD`` of the git checkout ``source_dir``."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source_dir), "archive", "--format=tar", "HEAD"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        raise VerificationError(
            f"cannot read the committed tree of {source_dir}: {exc} "
            f"{detail.decode('utf-8', 'replace').strip()}"
        ) from exc
    return _read_tar_stream(io.BytesIO(result.stdout), "r|")


def _one_suffix(files: dict[str, bytes], suffix: str) -> tuple[str, bytes]:
    """The one member that is ``suffix`` or ends in ``/`` + ``suffix``."""
    found = [
        (name, data)
        for name, data in files.items()
        if name == suffix or name.endswith(f"/{suffix}")
    ]
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


class PackageContract(NamedTuple):
    """What the committed ``pyproject.toml`` says the built metadata must hold."""

    requires_python: str
    requirements: frozenset[tuple[str, str | None]]
    scripts: Mapping[str, str]
    license_files: tuple[str, ...]


def _normalise_requirement(text: str) -> tuple[str, str | None]:
    """``(requirement, extra)`` with the PEP 503 name and no whitespace."""
    requirement, _, marker = text.partition(";")
    match = _NAME_RE.match(requirement.strip())
    if not match:
        raise VerificationError(f"unparseable requirement: {text!r}")
    name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
    rest = "".join(match.group(2).split()).lower()
    extra = _EXTRA_MARKER_RE.search(marker)
    return name + rest, extra.group(1) if extra else None


def package_contract(pyproject: bytes) -> PackageContract:
    """Read the metadata contract from the committed ``pyproject.toml``."""
    if tomllib is None:
        raise VerificationError("reading pyproject.toml needs Python 3.11+")
    try:
        project = tomllib.loads(pyproject.decode("utf-8"))["project"]
        license_file = project["license"]["file"]
        requirements = {
            _normalise_requirement(item) for item in project.get("dependencies", [])
        }
        for extra, items in project.get("optional-dependencies", {}).items():
            requirements |= {(_normalise_requirement(item)[0], extra) for item in items}
        return PackageContract(
            requires_python="".join(project["requires-python"].split()),
            requirements=frozenset(requirements),
            scripts=dict(project.get("scripts", {})),
            license_files=(license_file,),
        )
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise VerificationError(f"unreadable pyproject.toml contract: {exc}") from exc


def _compare_file_sets(label: str, actual: Iterable[str], expected: set[str]) -> None:
    found = set(actual)
    if found == expected:
        return
    details = []
    if expected - found:
        details.append(f"missing {', '.join(sorted(expected - found)[:5])}")
    if found - expected:
        details.append(f"unexpected {', '.join(sorted(found - expected)[:5])}")
    raise VerificationError(
        f"{label} file set does not match the commit: {'; '.join(details)}"
    )


def _headers(payload: bytes, label: str) -> email.message.Message:
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationError(f"{label} is not UTF-8") from exc
    return email.parser.BytesHeaderParser().parsebytes(payload)


def _validate_record(files: Mapping[str, bytes], record_name: str) -> None:
    """Every wheel file listed once in RECORD, with its size and SHA-256."""
    try:
        rows = list(csv.reader(io.StringIO(files[record_name].decode("utf-8"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise VerificationError("wheel RECORD is not a UTF-8 CSV file") from exc
    entries: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3:
            raise VerificationError(f"malformed RECORD row: {row!r}")
        path, digest, size = row
        if path in entries:
            raise VerificationError(f"duplicate RECORD entry: {path}")
        entries[path] = (digest, size)
    if set(entries) != set(files):
        raise VerificationError("wheel RECORD does not list exactly the wheel's files")
    for path, (digest, size) in entries.items():
        if path == record_name:
            if digest or size:
                raise VerificationError("RECORD must not hash itself")
            continue
        payload = files[path]
        expected = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
        algorithm, _, value = digest.partition("=")
        if algorithm != "sha256" or not hmac.compare_digest(
            value.encode("ascii", "replace"), expected.rstrip(b"=")
        ):
            raise VerificationError(f"RECORD hash does not match {path}")
        if size != str(len(payload)):
            raise VerificationError(f"RECORD size does not match {path}")


def _validate_wheel_metadata(
    files: Mapping[str, bytes], dist_info: str, version: str, contract: PackageContract
) -> None:
    wheel = _headers(files[f"{dist_info}/WHEEL"], "WHEEL")
    if (
        wheel.get("Wheel-Version") != "1.0"
        or wheel.get("Root-Is-Purelib") != "true"
        or wheel.get_all("Tag") != ["py3-none-any"]
    ):
        raise VerificationError("WHEEL is not a pure-Python py3-none-any wheel")

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # keep entry-point names' case
    try:
        parser.read_string(files[f"{dist_info}/entry_points.txt"].decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as exc:
        raise VerificationError("unreadable entry_points.txt") from exc
    entry_points = {section: dict(parser[section]) for section in parser.sections()}
    if entry_points != {"console_scripts": dict(contract.scripts)}:
        raise VerificationError("entry_points.txt does not match pyproject.toml")

    metadata = _headers(files[f"{dist_info}/METADATA"], "METADATA")
    requirements = {
        _normalise_requirement(item) for item in metadata.get_all("Requires-Dist", [])
    }
    if (
        metadata.get("Name") != PACKAGE
        or metadata.get("Version") != version
        or "".join(str(metadata.get("Requires-Python", "")).split())
        != contract.requires_python
        or requirements != contract.requirements
    ):
        raise VerificationError(
            "wheel METADATA name, version, or requirements do not match pyproject.toml"
        )


def validate_wheel_tree(
    files: Mapping[str, bytes],
    committed: Mapping[str, bytes],
    version: str,
    contract: PackageContract,
) -> None:
    """The wheel is the committed package plus its generated ``.dist-info``."""
    dist_info = f"{PACKAGE}-{version}.dist-info"
    package = {
        f"{PACKAGE}/{path.removeprefix(PACKAGE_SOURCE)}": data
        for path, data in committed.items()
        if path.startswith(PACKAGE_SOURCE)
    }
    licenses = {f"{dist_info}/licenses/{name}": name for name in contract.license_files}
    generated = {f"{dist_info}/{name}" for name in ("METADATA", "WHEEL", "RECORD")}
    generated.add(f"{dist_info}/entry_points.txt")
    _compare_file_sets("wheel", files, set(package) | set(licenses) | generated)
    for name, data in package.items():
        if name != f"{PACKAGE}/{BUILD_METADATA}" and files[name] != data:
            raise VerificationError(f"wheel file differs from the commit: {name}")
    for name, source in licenses.items():
        if files[name] != committed.get(source):
            raise VerificationError(f"wheel license differs from the commit: {name}")
    _validate_record(files, f"{dist_info}/RECORD")
    _validate_wheel_metadata(files, dist_info, version, contract)


def validate_sdist_tree(
    files: Mapping[str, bytes], committed: Mapping[str, bytes], version: str
) -> None:
    """The sdist is exactly the committed tree plus ``PKG-INFO``."""
    prefix = f"{PACKAGE}-{version}/"
    outside = sorted(name for name in files if not name.startswith(prefix))
    if outside:
        raise VerificationError(f"sdist member outside {prefix}: {outside[0]}")
    tree = {name.removeprefix(prefix): data for name, data in files.items()}
    _compare_file_sets("sdist", tree, set(committed) | {"PKG-INFO"})
    for name, data in tree.items():
        if name not in {"PKG-INFO", PACKAGE_SOURCE + BUILD_METADATA} and (
            data != committed[name]
        ):
            raise VerificationError(f"sdist file differs from the commit: {name}")


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
    *,
    require_release: bool = False,
) -> str:
    """Check the committed plugin tree; return the plugin version it must carry.

    That version is ``version`` only while the plugin content is the content
    recorded when the release was prepared, and a development version naming
    the content digest otherwise. ``require_release`` rejects the latter.
    """
    manifest_path = plugin_dir / ".skilldeck" / "content-manifest.json"
    release_path = plugin_dir / ".skilldeck" / "release.json"
    plugin_json_path = plugin_dir / ".claude-plugin" / "plugin.json"
    for path in (manifest_path, release_path, plugin_json_path):
        if path.is_symlink() or not path.is_file():
            raise VerificationError(f"missing or unsafe plugin file: {path}")
    plugin_manifest = _json_bytes(manifest_path.read_bytes(), "plugin manifest")
    if plugin_manifest != manifest:
        raise VerificationError("plugin and Python content manifests differ")
    plugin_json = _json_bytes(plugin_json_path.read_bytes(), "plugin.json")
    try:
        release = parse_plugin_release(
            _json_bytes(release_path.read_bytes(), "plugin release record")
        )
    except ValueError as exc:
        raise VerificationError(str(exc)) from exc
    if release["version"] != version:
        raise VerificationError(
            f"plugin release record is for {release['version']}, not {version}"
        )

    records = _validate_manifest_shape(plugin_manifest, version)
    expected = {record["name"] for record in records}
    skills_root = plugin_dir / "skills"
    expected_paths = {
        ".claude-plugin/plugin.json",
        ".skilldeck/content-manifest.json",
        ".skilldeck/release.json",
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
    try:
        plugin_files = {
            ".skilldeck/content-manifest.json": manifest_path.read_text(
                encoding="utf-8"
            )
        }
    except UnicodeDecodeError as exc:
        raise VerificationError("non-UTF-8 plugin content manifest") from exc
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
        plugin_files[f"skills/{record['name']}/SKILL.md"] = text
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
    digest = claude_plugin_content_digest(plugin_json, plugin_files)
    plugin_version = claude_plugin_version(version, digest, release)
    if require_release and plugin_version != version:
        raise VerificationError(
            f"plugin is development snapshot {plugin_version}, not release "
            f"{version}: its content changed after the release was prepared "
            "(see docs/releasing.md)"
        )
    if plugin_json != claude_plugin_metadata(plugin_version, derived):
        raise VerificationError("plugin metadata does not match generated contract")
    return plugin_version


def verify(
    wheel: Path,
    sdist: Path,
    plugin_dir: Path,
    version: str,
    source_ref: str,
    source_commit: str,
    *,
    source_dir: Path = ROOT,
    require_release_plugin: bool = False,
) -> str:
    """Run every check; return the plugin version the committed tree carries."""
    if wheel.name != f"{PACKAGE}-{version}-py3-none-any.whl":
        raise VerificationError(f"unexpected wheel filename: {wheel.name}")
    if sdist.name != f"{PACKAGE}-{version}.tar.gz":
        raise VerificationError(f"unexpected sdist filename: {sdist.name}")
    committed = read_committed_tree(source_dir)
    if "pyproject.toml" not in committed:
        raise VerificationError("the committed tree has no pyproject.toml")
    contract = package_contract(committed["pyproject.toml"])

    wheel_files = read_zip(wheel)
    sdist_files = read_tar(sdist)
    validate_wheel_tree(wheel_files, committed, version, contract)
    validate_sdist_tree(sdist_files, committed, version)
    if (
        wheel_files[f"{PACKAGE}-{version}.dist-info/METADATA"]
        != sdist_files[f"{PACKAGE}-{version}/PKG-INFO"]
    ):
        raise VerificationError("wheel METADATA and sdist PKG-INFO differ")

    wheel_manifest = validate_distribution(
        wheel_files,
        marker=PACKAGE,
        version=version,
        source_ref=source_ref,
        source_commit=source_commit,
    )
    sdist_manifest = validate_distribution(
        sdist_files,
        marker=PACKAGE_SOURCE.rstrip("/"),
        version=version,
        source_ref=source_ref,
        source_commit=source_commit,
    )
    if wheel_manifest != sdist_manifest:
        raise VerificationError("wheel and sdist content manifests differ")
    return validate_plugin(
        plugin_dir,
        wheel_manifest,
        _distribution_skills(wheel_files, PACKAGE),
        version,
        require_release=require_release_plugin,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-ref", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT,
        help="git checkout whose HEAD the distributions were built from",
    )
    parser.add_argument(
        "--release-plugin",
        action="store_true",
        help="require the plugin to be exactly the prepared release, "
        "not a development snapshot",
    )
    args = parser.parse_args()
    try:
        plugin_version = verify(
            args.wheel,
            args.sdist,
            args.plugin_dir,
            args.expected_version,
            args.expected_ref,
            args.expected_commit,
            source_dir=args.source_dir,
            require_release_plugin=args.release_plugin,
        )
    except (OSError, VerificationError, tarfile.TarError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(
        f"ok: wheel and sdist match the commit and {args.expected_ref} "
        f"at {args.expected_commit}; plugin version {plugin_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
