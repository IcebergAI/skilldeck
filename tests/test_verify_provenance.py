"""Tests for scripts/verify_provenance.py (installed-distribution identity)."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck import __version__
from skilldeck.cli import cli

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "verify_provenance.py"
_spec = importlib.util.spec_from_file_location("verify_provenance", _SCRIPT)
assert _spec and _spec.loader
provenance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(provenance)

REF = f"refs/tags/v{__version__}"
COMMIT = "a" * 40


@pytest.fixture
def manifest():
    return json.loads(provenance.CONTENT_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture
def report():
    """Real ``provenance --json`` output, as a stamped release build reports it."""
    result = CliRunner().invoke(cli, ["provenance", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    data["distribution"]["source_ref"] = REF
    data["distribution"]["source_commit"] = COMMIT
    return data


def _verify(report, manifest, **overrides):
    expected = {"version": __version__, "source_ref": REF, "source_commit": COMMIT}
    expected.update(overrides)
    provenance.verify(report, manifest, **expected)


def test_accepts_the_expected_identity(report, manifest):
    _verify(report, manifest)


@pytest.mark.parametrize(
    "field, value",
    [
        ("version", "0.0.0"),
        ("source_ref", "refs/tags/v0.0.0"),
        ("source_commit", "b" * 40),
    ],
)
def test_rejects_a_different_expected_identity(report, manifest, field, value):
    with pytest.raises(provenance.ProvenanceError):
        _verify(report, manifest, **{field: value})


def test_rejects_an_unstamped_install(report, manifest):
    report["distribution"]["source_ref"] = None
    report["distribution"]["source_commit"] = None
    with pytest.raises(provenance.ProvenanceError, match="installed distribution"):
        _verify(report, manifest)


def test_rejects_skills_that_differ_from_the_committed_manifest(report, manifest):
    tampered = copy.deepcopy(report)
    tampered["skills"][0]["canonical_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(provenance.ProvenanceError, match="content manifest"):
        _verify(tampered, manifest)

    missing = copy.deepcopy(report)
    missing["skills"].pop()
    with pytest.raises(provenance.ProvenanceError, match="content manifest"):
        _verify(missing, manifest)


def test_rejects_malformed_reports(manifest):
    with pytest.raises(provenance.ProvenanceError, match="unsupported"):
        _verify([], manifest)
    with pytest.raises(provenance.ProvenanceError, match="unsupported"):
        _verify({"schema_version": 2}, manifest)


def test_rejects_invalid_json_file(tmp_path):
    path = tmp_path / "provenance.json"
    path.write_bytes(b"\xff not json")
    with pytest.raises(provenance.ProvenanceError, match="not valid UTF-8 JSON"):
        provenance._load(path)
