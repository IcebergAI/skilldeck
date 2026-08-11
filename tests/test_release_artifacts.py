import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

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
    (tmp_path / "skilldeck-1.2.3.spdx.json").write_text("{}\n")
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
    (directory / "unexpected.txt").write_text("no")
    with pytest.raises(checksums.ChecksumError, match="unexpected"):
        checksums.verify(output)
    (directory / "unexpected.txt").unlink()
    output.write_text("not a checksum\n")
    with pytest.raises(checksums.ChecksumError, match="malformed"):
        checksums.verify(output)


def test_checksum_set_rejects_symlinked_artifact(tmp_path):
    directory = _release_dir(tmp_path)
    wheel = directory / "skilldeck-1.2.3-py3-none-any.whl"
    wheel.unlink()
    wheel.symlink_to(directory / "skilldeck-1.2.3.tar.gz")
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
        )
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


def test_verifiers_reject_symlink_inputs(tmp_path):
    directory = tmp_path / "bundle"
    directory.mkdir()
    directory = _release_dir(directory)
    checksums_path = checksums.write(directory)
    checksum_link = tmp_path / "SHA256SUMS"
    checksum_link.symlink_to(checksums_path)
    with pytest.raises(checksums.ChecksumError, match="regular file"):
        checksums.verify(checksum_link)

    valid = _sbom(tmp_path, ["skilldeck", "click", "PyYAML"])
    sbom_link = tmp_path / "linked.spdx.json"
    sbom_link.symlink_to(valid)
    with pytest.raises(sbom.SbomError, match="regular file"):
        sbom.verify(sbom_link)
