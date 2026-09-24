import importlib.util
import io
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from skilldeck.provenance import claude_plugin_content_digest

_ROOT = Path(__file__).resolve().parent.parent


def _script(name: str):
    path = _ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checksums = _script("write_checksums.py")
identity = _script("verify_distribution_identity.py")
sbom = _script("verify_sbom.py")


def _release_dir(tmp_path: Path) -> Path:
    (tmp_path / "skilldeck-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "skilldeck-1.2.3.tar.gz").write_bytes(b"sdist")
    (tmp_path / "skilldeck-1.2.3.spdx.json").write_text("{}\n", encoding="utf-8")
    return tmp_path


def test_checksum_round_trip_and_tamper_failure(tmp_path):
    directory = _release_dir(tmp_path)
    output = checksums.write(directory)
    checksums.verify(output)
    wheel = directory / "skilldeck-1.2.3-py3-none-any.whl"
    wheel.write_bytes(wheel.read_bytes() + b"tampered")
    with pytest.raises(checksums.ChecksumError, match="checksum mismatch"):
        checksums.verify(output)


def test_checksum_set_rejects_missing_extra_and_malformed_entries(tmp_path):
    directory = _release_dir(tmp_path)
    output = checksums.write(directory)
    (directory / "unexpected.txt").write_text("no", encoding="utf-8")
    with pytest.raises(checksums.ChecksumError, match="unexpected"):
        checksums.verify(output)
    (directory / "unexpected.txt").unlink()
    output.write_text("not a checksum\n", encoding="utf-8")
    with pytest.raises(checksums.ChecksumError, match="malformed"):
        checksums.verify(output)


def test_checksum_set_rejects_symlinked_artifact(tmp_path, symlink):
    directory = _release_dir(tmp_path)
    wheel = directory / "skilldeck-1.2.3-py3-none-any.whl"
    wheel.unlink()
    symlink(wheel, directory / "skilldeck-1.2.3.tar.gz")
    with pytest.raises(checksums.ChecksumError, match="regular file"):
        checksums.write(directory)


def test_archive_reader_rejects_traversal_and_links(tmp_path):
    unsafe_zip = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(unsafe_zip, "w") as archive:
        archive.writestr("../escape", b"bad")
    with pytest.raises(identity.VerificationError, match="unsafe"):
        identity.read_zip(unsafe_zip)

    unsafe_tar = tmp_path / "unsafe.tar.gz"
    with tarfile.open(unsafe_tar, "w:gz") as archive:
        link = tarfile.TarInfo("safe-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/tmp/target"
        archive.addfile(link)
    with pytest.raises(identity.VerificationError, match="non-regular"):
        identity.read_tar(unsafe_tar)


def test_archive_reader_rejects_duplicate_member(tmp_path):
    duplicate = tmp_path / "duplicate.whl"
    with (
        pytest.warns(UserWarning, match="Duplicate name"),
        zipfile.ZipFile(duplicate, "w") as archive,
    ):
        archive.writestr("same", b"one")
        archive.writestr("same", b"two")
    with pytest.raises(identity.VerificationError, match="duplicate"):
        identity.read_zip(duplicate)


def test_archive_reader_accepts_regular_files(tmp_path):
    archive_path = tmp_path / "safe.tar.gz"
    payload = b"content"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("root/file.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    assert identity.read_tar(archive_path) == {"root/file.txt": payload}


@pytest.mark.parametrize(
    "suffix, writer, reader",
    [
        ("whl", zipfile.ZipFile, identity.read_zip),
        ("tar.gz", tarfile.open, identity.read_tar),
    ],
)
def test_archive_reader_rejects_excessive_member_count(
    tmp_path, suffix, writer, reader
):
    path = tmp_path / f"many.{suffix}"
    if suffix == "whl":
        with writer(path, "w") as archive:
            for index in range(identity.MAX_ARCHIVE_MEMBERS + 1):
                archive.writestr(f"root/{index}", b"x")
    else:
        with writer(path, "w:gz") as archive:
            for index in range(identity.MAX_ARCHIVE_MEMBERS + 1):
                member = tarfile.TarInfo(f"root/{index}")
                member.size = 1
                archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(identity.VerificationError, match="too many"):
        reader(path)


def _sbom(tmp_path: Path, names: list[str]) -> Path:
    path = tmp_path / "release.spdx.json"
    path.write_text(
        json.dumps(
            {
                "spdxVersion": "SPDX-2.3",
                "packages": [
                    {"name": name, "SPDXID": f"SPDXRef-{index}"}
                    for index, name in enumerate(names)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_sbom_requires_runtime_and_excludes_development_packages(tmp_path):
    valid = _sbom(tmp_path, ["skilldeck", "click", "PyYAML"])
    sbom.verify(valid)
    valid.unlink()

    missing = _sbom(tmp_path, ["skilldeck", "click"])
    with pytest.raises(sbom.SbomError, match="missing runtime"):
        sbom.verify(missing)
    missing.unlink()

    polluted = _sbom(tmp_path, ["skilldeck", "click", "PyYAML", "pytest"])
    with pytest.raises(sbom.SbomError, match="development"):
        sbom.verify(polluted)


def test_verifiers_reject_symlink_inputs(tmp_path, symlink):
    directory = tmp_path / "bundle"
    directory.mkdir()
    directory = _release_dir(directory)
    checksums_path = checksums.write(directory)
    checksum_link = tmp_path / "SHA256SUMS"
    symlink(checksum_link, checksums_path)
    with pytest.raises(checksums.ChecksumError, match="regular file"):
        checksums.verify(checksum_link)

    valid = _sbom(tmp_path, ["skilldeck", "click", "PyYAML"])
    sbom_link = tmp_path / "linked.spdx.json"
    symlink(sbom_link, valid)
    with pytest.raises(sbom.SbomError, match="regular file"):
        sbom.verify(sbom_link)


# --- digest handoff between release jobs (#109) --------------------------------


def _bundle(tmp_path: Path) -> Path:
    directory = _release_dir(tmp_path)
    checksums.write(directory)
    return directory


def test_bundle_digests_round_trip_through_a_job_output(tmp_path):
    directory = _bundle(tmp_path)
    digests = checksums.bundle_digests(directory)
    assert set(digests) == {
        "SHA256SUMS",
        "skilldeck-1.2.3-py3-none-any.whl",
        "skilldeck-1.2.3.tar.gz",
        "skilldeck-1.2.3.spdx.json",
    }
    text = json.dumps(digests, sort_keys=True, separators=(",", ":"))
    assert "\n" not in text  # fits a single GITHUB_OUTPUT line
    checksums.verify_digests(directory, checksums.parse_digests(text))


def test_expected_digests_catch_a_bundle_whose_checksums_were_rewritten(tmp_path):
    directory = _bundle(tmp_path)
    digests = checksums.bundle_digests(directory)
    # tampering that also rewrites SHA256SUMS passes the in-bundle check...
    wheel = directory / "skilldeck-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"evil")
    checksums.write(directory)
    checksums.verify(directory / "SHA256SUMS")
    # ...but not the digests the build job handed over out of band
    with pytest.raises(checksums.ChecksumError, match="differs from the build job"):
        checksums.verify_digests(directory, digests)


def test_expected_digests_require_the_exact_file_set(tmp_path):
    directory = _bundle(tmp_path)
    digests = checksums.bundle_digests(directory)
    (directory / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(checksums.ChecksumError, match="unexpected: extra.txt"):
        checksums.verify_digests(directory, digests)
    (directory / "extra.txt").unlink()
    (directory / "SHA256SUMS").unlink()
    with pytest.raises(checksums.ChecksumError, match="missing: SHA256SUMS"):
        checksums.verify_digests(directory, digests)


@pytest.mark.parametrize(
    "text",
    ["", "[]", "{}", '{"a": "b"}', '{"../x": "' + "0" * 64 + '"}', '{"a": 1}'],
)
def test_expected_digests_must_be_well_formed(text):
    with pytest.raises(checksums.ChecksumError):
        checksums.parse_digests(text)


# --- wheel and sdist contents against the commit (#109) -------------------------

VERSION = "1.2.3"
DIST_INFO = f"skilldeck-{VERSION}.dist-info"
CONTRACT = identity.PackageContract(
    requires_python=">=3.10",
    requirements=frozenset({("click>=8.1", ""), ("pytest>=9.0", "extra == 'dev'")}),
    extras=frozenset({"dev"}),
    scripts={"skilldeck": "skilldeck.cli:main"},
    license_files=("LICENSE",),
)
COMMITTED = {
    "pyproject.toml": b"[project]\n",
    "LICENSE": b"MIT License\n",
    "README.md": b"# skilldeck\n",
    "src/skilldeck/__init__.py": b"",
    "src/skilldeck/cli.py": b"def main():\n    pass\n",
    "src/skilldeck/_build_metadata.json": b'{"source_ref": null}\n',
    "src/skilldeck/skills/demo/skill.md": b"# demo\n",
}
METADATA = (
    b"Metadata-Version: 2.4\nName: skilldeck\nVersion: 1.2.3\n"
    b"Requires-Python: >=3.10\nRequires-Dist: click>=8.1\nProvides-Extra: dev\n"
    b"Requires-Dist: pytest>=9.0; extra == 'dev'\n\nA long description.\n"
)


def _record(files: dict[str, bytes], name: str) -> bytes:
    rows = []
    for path, data in files.items():
        digest = identity.base64.urlsafe_b64encode(
            identity.hashlib.sha256(data).digest()
        )
        rows.append(f"{path},sha256={digest.rstrip(b'=').decode()},{len(data)}")
    return ("\n".join([*rows, f"{name},,"]) + "\n").encode()


def _wheel(committed=COMMITTED, *, extra=None, metadata=METADATA, drop=()):
    files = {
        f"skilldeck/{path.removeprefix('src/skilldeck/')}": data
        for path, data in committed.items()
        if path.startswith("src/skilldeck/")
    }
    files["skilldeck/_build_metadata.json"] = b'{"source_ref": "stamped"}\n'
    files[f"{DIST_INFO}/METADATA"] = metadata
    files[f"{DIST_INFO}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
        b"Tag: py3-none-any\n"
    )
    files[f"{DIST_INFO}/entry_points.txt"] = (
        b"[console_scripts]\nskilldeck = skilldeck.cli:main\n"
    )
    files[f"{DIST_INFO}/licenses/LICENSE"] = committed["LICENSE"]
    files.update(extra or {})
    for name in drop:
        del files[name]
    files[f"{DIST_INFO}/RECORD"] = _record(files, f"{DIST_INFO}/RECORD")
    return files


def _sdist(committed=COMMITTED, **extra):
    files = {f"skilldeck-{VERSION}/{path}": data for path, data in committed.items()}
    files[f"skilldeck-{VERSION}/src/skilldeck/_build_metadata.json"] = b"stamped\n"
    files[f"skilldeck-{VERSION}/PKG-INFO"] = METADATA
    files.update(extra)
    return files


def test_wheel_built_from_the_commit_passes():
    identity.validate_wheel_tree(_wheel(), COMMITTED, VERSION, CONTRACT)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"skilldeck/backdoor.py": b"import os\n"}, "unexpected skilldeck/backdoor.py"),
        (
            {"skilldeck-hook.pth": b"import skilldeck\n"},
            "unexpected skilldeck-hook.pth",
        ),
        (
            {"skilldeck/cli.py": b"def main():\n    steal()\n"},
            "differs from the commit",
        ),
        ({f"{DIST_INFO}/licenses/LICENSE": b"GPL\n"}, "license differs"),
        (
            {f"{DIST_INFO}/entry_points.txt": b"[console_scripts]\nx = evil:main\n"},
            "entry_points.txt",
        ),
        (
            {
                f"{DIST_INFO}/WHEEL": (
                    b"Wheel-Version: 1.0\nTag: cp314-cp314-linux_x86_64\n"
                )
            },
            "py3-none-any",
        ),
        (
            {
                f"{DIST_INFO}/METADATA": METADATA.replace(
                    b"\n\n", b"\nRequires-Dist: evil\n\n"
                )
            },
            "requirements",
        ),
        (
            {f"{DIST_INFO}/METADATA": METADATA.replace(b"1.2.3", b"1.2.4")},
            "version",
        ),
        # a marker that drops a runtime dependency everywhere...
        (
            {
                f"{DIST_INFO}/METADATA": METADATA.replace(
                    b"click>=8.1\n", b'click>=8.1; python_version < "3"\n'
                )
            },
            "requirements",
        ),
        # ...or turns a dev-only dependency into a runtime one
        (
            {
                f"{DIST_INFO}/METADATA": METADATA.replace(
                    b"extra == 'dev'", b"extra == 'dev' or python_version >= \"3\""
                )
            },
            "requirements",
        ),
        (
            {f"{DIST_INFO}/METADATA": METADATA.replace(b"Provides-Extra: dev\n", b"")},
            "extras",
        ),
    ],
)
def test_wheel_contents_that_differ_from_the_commit_fail(extra, message):
    # RECORD is regenerated to match, as a tampering build would
    with pytest.raises(identity.VerificationError, match=message):
        identity.validate_wheel_tree(_wheel(extra=extra), COMMITTED, VERSION, CONTRACT)


def test_wheel_missing_a_committed_module_fails():
    files = _wheel(drop=["skilldeck/cli.py"])
    with pytest.raises(identity.VerificationError, match="missing skilldeck/cli.py"):
        identity.validate_wheel_tree(files, COMMITTED, VERSION, CONTRACT)


def test_wheel_record_must_hash_every_file():
    files = _wheel()
    record = files[f"{DIST_INFO}/RECORD"].decode()
    good = (
        identity.base64.urlsafe_b64encode(
            identity.hashlib.sha256(COMMITTED["src/skilldeck/cli.py"]).digest()
        )
        .rstrip(b"=")
        .decode()
    )

    wrong_hash = dict(files)
    wrong_hash[f"{DIST_INFO}/RECORD"] = record.replace(good, "A" * len(good)).encode()
    with pytest.raises(identity.VerificationError, match="RECORD hash"):
        identity.validate_wheel_tree(wrong_hash, COMMITTED, VERSION, CONTRACT)

    size = len(COMMITTED["src/skilldeck/cli.py"])
    wrong_size = dict(files)
    wrong_size[f"{DIST_INFO}/RECORD"] = record.replace(
        f"{good},{size}", f"{good},{size + 1}"
    ).encode()
    with pytest.raises(identity.VerificationError, match="RECORD size"):
        identity.validate_wheel_tree(wrong_size, COMMITTED, VERSION, CONTRACT)

    unlisted = dict(files)
    unlisted[f"{DIST_INFO}/RECORD"] = "\n".join(
        line for line in record.splitlines() if not line.startswith("skilldeck/cli.py")
    ).encode()
    with pytest.raises(identity.VerificationError, match="does not list exactly"):
        identity.validate_wheel_tree(unlisted, COMMITTED, VERSION, CONTRACT)


def test_sdist_is_exactly_the_committed_tree_plus_pkg_info():
    identity.validate_sdist_tree(_sdist(), COMMITTED, VERSION)
    for extra, message in (
        ({f"skilldeck-{VERSION}/src/skilldeck/evil.py": b"x"}, "unexpected"),
        ({f"skilldeck-{VERSION}/README.md": b"changed\n"}, "differs from the commit"),
        ({"elsewhere/README.md": b"x"}, "outside"),
    ):
        with pytest.raises(identity.VerificationError, match=message):
            identity.validate_sdist_tree(_sdist(**extra), COMMITTED, VERSION)
    missing = _sdist()
    del missing[f"skilldeck-{VERSION}/LICENSE"]
    with pytest.raises(identity.VerificationError, match="missing LICENSE"):
        identity.validate_sdist_tree(missing, COMMITTED, VERSION)


def test_one_suffix_matches_only_whole_path_components():
    files = {
        "evil-src/skilldeck/_content_manifest.json": b"evil",
        "skilldeck-1.2.3/src/skilldeck/_content_manifest.json": b"real",
    }
    assert identity._one_suffix(files, "src/skilldeck/_content_manifest.json") == (
        "skilldeck-1.2.3/src/skilldeck/_content_manifest.json",
        b"real",
    )
    assert identity._one_suffix(
        {"skilldeck/_content_manifest.json": b"wheel"},
        "skilldeck/_content_manifest.json",
    ) == ("skilldeck/_content_manifest.json", b"wheel")
    with pytest.raises(identity.VerificationError, match="expected exactly one"):
        identity._one_suffix(
            {"xskilldeck/_build_metadata.json": b""}, "skilldeck/_build_metadata.json"
        )


def test_requirements_are_compared_by_normalised_name_and_marker():
    assert identity._normalise_requirement('types-PyYAML >= 6.0 ; extra == "dev"') == (
        "types-pyyaml>=6.0",
        "extra == 'dev'",
    )
    assert identity._normalise_requirement("Foo_Bar.baz>=1") == ("foo-bar-baz>=1", "")
    # hatchling's spelling of a marked optional dependency matches pyproject's
    assert identity._normalise_requirement(
        "tomli; (python_version<'3.11') and extra == 'dev'"
    ) == ("tomli", identity._extra_marker('python_version < "3.11"', "dev"))
    # a changed marker is a different requirement
    assert identity._normalise_requirement(
        "pytest; extra == 'dev' or python_version >= '3'"
    ) != identity._normalise_requirement("pytest; extra == 'dev'")


@pytest.mark.parametrize("marker", ["x @ y", 'os_name == "a\'b"', "a == 'open"])
def test_unparseable_markers_are_rejected(marker):
    with pytest.raises(identity.VerificationError, match="marker"):
        identity._normalise_requirement(f"pkg; {marker}")


needs_tomllib = pytest.mark.skipif(
    identity.tomllib is None, reason="reading pyproject.toml needs Python 3.11+"
)


@needs_tomllib
def test_package_contract_reads_the_committed_pyproject():
    contract = identity.package_contract((_ROOT / "pyproject.toml").read_bytes())
    assert ("click>=8.1", "") in contract.requirements
    assert ("types-pyyaml>=6.0", "extra == 'dev'") in contract.requirements
    assert contract.extras == {"dev"}
    assert contract.scripts == {"skilldeck": "skilldeck.cli:main"}
    assert contract.license_files == ("LICENSE",)


# --- the committed tree, the plugin, and the whole verifier ---------------------


def _git_tree():
    """The repository's committed tree and its ``HEAD`` commit."""
    try:
        commit = identity._git(_ROOT, "rev-parse", "HEAD").decode().strip()
        return identity.read_committed_tree(_ROOT, commit), commit
    except (OSError, subprocess.CalledProcessError, identity.VerificationError) as exc:
        pytest.skip(f"not a git checkout: {exc}")


def test_committed_tree_is_read_from_head_not_the_working_tree(tmp_path):
    def git(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
            + ["-c", "commit.gpgsign=false", *args],
            capture_output=True,
            check=True,
        )

    try:
        git("init", "-q")
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git is unavailable: {exc}")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_bytes(b"committed")
    git("add", "-A")
    git("commit", "-q", "-m", "c")
    # a build step editing the checkout changes neither what was committed...
    (tmp_path / "src" / "code.py").write_bytes(b"edited")
    (tmp_path / "src" / "injected.py").write_bytes(b"new")
    head = identity._git(tmp_path, "rev-parse", "HEAD").decode().strip()
    assert identity.read_committed_tree(tmp_path, head) == {"src/code.py": b"committed"}
    # ...nor can a directory without a commit stand in for one
    with pytest.raises(identity.VerificationError, match="committed tree"):
        identity.read_committed_tree(tmp_path / "src" / "missing", head)
    # ...nor a checkout of some other commit than the expected one
    git("commit", "-q", "--allow-empty", "-m", "later")
    with pytest.raises(identity.VerificationError, match="not the expected commit"):
        identity.read_committed_tree(tmp_path, head)
    with pytest.raises(identity.VerificationError, match="invalid expected commit"):
        identity.read_committed_tree(tmp_path, "HEAD")


def _canonical_skills(root: Path) -> dict[str, dict[str, str]]:
    return {
        skill.name: {
            name: (skill / name).read_text(encoding="utf-8")
            for name in ("meta.yaml", "skill.md")
        }
        for skill in (root / "src" / "skilldeck" / "skills").iterdir()
    }


def _plugin_copy(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "claude-plugin"
    shutil.copytree(_ROOT / "claude-plugin", plugin_dir)
    return plugin_dir


def _as_release(plugin_dir: Path, version: str) -> None:
    """Rewrite a plugin copy as if its content had been prepared for release."""
    plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
    plugin = json.loads(plugin_json.read_text(encoding="utf-8"))
    files = {
        path.relative_to(plugin_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in plugin_dir.rglob("*")
        if path.is_file() and path.name not in {"plugin.json", "release.json"}
    }
    record = {
        "content_sha256": claude_plugin_content_digest(plugin, files),
        "schema_version": 1,
        "version": version,
    }
    (plugin_dir / ".skilldeck" / "release.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    plugin_json.write_text(json.dumps({**plugin, "version": version}), "utf-8")


def _manifest() -> dict:
    return json.loads(
        (_ROOT / "src" / "skilldeck" / "_content_manifest.json").read_text("utf-8")
    )


def test_plugin_release_check_accepts_only_the_prepared_release(tmp_path):
    manifest = _manifest()
    version = manifest["package_version"]
    skills = _canonical_skills(_ROOT)
    plugin_dir = _plugin_copy(tmp_path)
    plugin = json.loads(
        (plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    derived = identity.validate_plugin(plugin_dir, manifest, skills, version)
    assert derived == plugin["version"]
    if derived != version:  # main between releases: a development snapshot
        with pytest.raises(identity.VerificationError, match="development snapshot"):
            identity.validate_plugin(
                plugin_dir, manifest, skills, version, require_release=True
            )

    _as_release(plugin_dir, version)
    assert (
        identity.validate_plugin(
            plugin_dir, manifest, skills, version, require_release=True
        )
        == version
    )
    # content that changed since the release was prepared (here, bytes of a
    # file whose parsed JSON is unchanged) may not keep the release version
    manifest_path = plugin_dir / ".skilldeck" / "content-manifest.json"
    manifest_path.write_text(manifest_path.read_text("utf-8") + "\n", "utf-8")
    with pytest.raises(identity.VerificationError, match="plugin metadata"):
        identity.validate_plugin(plugin_dir, manifest, skills, version)


def test_plugin_release_record_must_name_the_package_version(tmp_path):
    manifest = _manifest()
    plugin_dir = _plugin_copy(tmp_path)
    record = plugin_dir / ".skilldeck" / "release.json"
    record.write_text(
        json.dumps({"content_sha256": None, "schema_version": 1, "version": "0.0.1"}),
        encoding="utf-8",
    )
    with pytest.raises(identity.VerificationError, match="release record is for"):
        identity.validate_plugin(
            plugin_dir, manifest, _canonical_skills(_ROOT), manifest["package_version"]
        )
    record.unlink()
    with pytest.raises(identity.VerificationError, match="missing or unsafe"):
        identity.validate_plugin(
            plugin_dir, manifest, _canonical_skills(_ROOT), manifest["package_version"]
        )


def _write_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def _write_tar(path: Path, files: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return path


@needs_tomllib
def test_verify_accepts_distributions_of_the_commit_and_rejects_a_pth(tmp_path):
    committed, commit = _git_tree()
    contract = identity.package_contract(committed["pyproject.toml"])
    version = identity.tomllib.loads(committed["pyproject.toml"].decode())["project"][
        "version"
    ]
    ref = f"refs/tags/v{version}"
    stamped = json.dumps(
        {
            "schema_version": 1,
            "source_commit": commit,
            "source_ref": ref,
            "source_repository": "https://github.com/IcebergAI/skilldeck",
        }
    ).encode()
    metadata = "".join(
        [
            f"Metadata-Version: 2.4\nName: skilldeck\nVersion: {version}\n",
            f"Requires-Python: {contract.requires_python}\n",
            *(f"Provides-Extra: {extra}\n" for extra in sorted(contract.extras)),
            *(
                f"Requires-Dist: {requirement}"
                + (f"; {marker}" if marker else "")
                + "\n"
                for requirement, marker in sorted(
                    contract.requirements, key=lambda item: (item[1], item[0])
                )
            ),
            "\nDescription.\n",
        ]
    ).encode()
    dist_info = f"skilldeck-{version}.dist-info"
    package = {
        f"skilldeck/{path.removeprefix('src/skilldeck/')}": data
        for path, data in committed.items()
        if path.startswith("src/skilldeck/")
    }
    package["skilldeck/_build_metadata.json"] = stamped
    package[f"{dist_info}/METADATA"] = metadata
    package[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    package[f"{dist_info}/entry_points.txt"] = b"".join(
        [b"[console_scripts]\n"]
        + [f"{k} = {v}\n".encode() for k, v in contract.scripts.items()]
    )
    package[f"{dist_info}/licenses/LICENSE"] = committed["LICENSE"]
    wheel_files = dict(package)
    wheel_files[f"{dist_info}/RECORD"] = _record(package, f"{dist_info}/RECORD")
    sdist_files = {f"skilldeck-{version}/{p}": d for p, d in committed.items()}
    sdist_files[f"skilldeck-{version}/src/skilldeck/_build_metadata.json"] = stamped
    sdist_files[f"skilldeck-{version}/PKG-INFO"] = metadata

    plugin_dir = tmp_path / "claude-plugin"
    for name, data in committed.items():
        if name.startswith("claude-plugin/"):
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    wheel = _write_zip(tmp_path / f"skilldeck-{version}-py3-none-any.whl", wheel_files)
    sdist = _write_tar(tmp_path / f"skilldeck-{version}.tar.gz", sdist_files)

    plugin_version = identity.verify(
        wheel, sdist, plugin_dir, version, ref, commit, source_dir=_ROOT
    )
    assert plugin_version.startswith(version.rsplit(".", 1)[0])

    hooked = dict(package)
    hooked["skilldeck-hook.pth"] = b"import os; os.system('id')\n"
    hooked[f"{dist_info}/RECORD"] = _record(hooked, f"{dist_info}/RECORD")
    _write_zip(wheel, hooked)
    with pytest.raises(identity.VerificationError, match="skilldeck-hook.pth"):
        identity.verify(
            wheel, sdist, plugin_dir, version, ref, commit, source_dir=_ROOT
        )
