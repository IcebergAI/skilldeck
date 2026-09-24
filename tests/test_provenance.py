import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from skilldeck import provenance
from skilldeck.cli import cli
from skilldeck.provenance import (
    canonical_skill_digest,
    claude_plugin_content_digest,
    claude_plugin_version,
    content_manifest,
    normalise_text,
    parse_plugin_release,
    sha256_text,
    verify_bundled_skills,
)
from skilldeck.registry import DEFAULT_SKILLS_DIR, Skill


def _skill(tmp_path: Path, name: str) -> Skill:
    root = tmp_path / name
    root.mkdir()
    (root / "meta.yaml").write_text(
        f"name: {name}\ndescription: Example\ncategory: review\n"
        "version: 1.2.3\nsupported-agents:\n  - claude\n",
        encoding="utf-8",
    )
    body = f"# {name}\n\nReview carefully.\n"
    (root / "skill.md").write_text(body, encoding="utf-8")
    return Skill(
        name=name,
        description="Example",
        category="review",
        version="1.2.3",
        supported_agents=("claude",),
        body=body,
        path=root,
    )


def test_provenance_hashes_normalise_newlines():
    assert normalise_text("a\r\nb\rc\n") == "a\nb\nc\n"
    assert sha256_text("a\r\nb\r") == sha256_text("a\nb\n")
    assert canonical_skill_digest("name: x\r\n", "body\r\n") == (
        canonical_skill_digest("name: x\n", "body\n")
    )


def test_canonical_digest_is_domain_separated_and_sensitive():
    baseline = canonical_skill_digest("ab", "c")
    assert baseline != canonical_skill_digest("a", "bc")
    assert baseline != canonical_skill_digest("ab ", "c")
    assert baseline != canonical_skill_digest("ab", "c ")
    assert baseline.startswith("sha256:")


def test_content_manifest_is_sorted_and_deterministic(tmp_path):
    second = _skill(tmp_path, "zeta")
    first = _skill(tmp_path, "alpha")
    left = content_manifest("9.8.7", [second, first])
    right = content_manifest("9.8.7", [first, second])
    assert left == right
    assert [record["name"] for record in left["skills"]] == ["alpha", "zeta"]
    assert all(
        record["canonical_sha256"].startswith("sha256:") for record in left["skills"]
    )


def test_content_manifest_rejects_duplicate_skill_names(tmp_path):
    skill = _skill(tmp_path, "same")
    with pytest.raises(ValueError, match="duplicate skill"):
        content_manifest("1.0.0", [skill, skill])


# --- Claude plugin version (#111) ----------------------------------------------

_DIGEST = "sha256:" + "ab" * 32
_METADATA = {"name": "skilldeck", "version": "1.2.3", "description": "d"}


def _release(version="1.2.3", digest=_DIGEST):
    return {"schema_version": 1, "version": version, "content_sha256": digest}


def test_plugin_content_digest_ignores_only_the_version():
    files = {"skills/a/SKILL.md": "body\n"}
    baseline = claude_plugin_content_digest(_METADATA, files)
    assert baseline == claude_plugin_content_digest(
        {**_METADATA, "version": "9.9.9"}, files
    )
    assert baseline == claude_plugin_content_digest(
        _METADATA, {"skills/a/SKILL.md": "body\r\n"}
    )
    assert baseline != claude_plugin_content_digest(
        {**_METADATA, "description": "e"}, files
    )
    assert baseline != claude_plugin_content_digest(
        _METADATA, {"skills/a/SKILL.md": "body!\n"}
    )
    assert baseline != claude_plugin_content_digest(
        _METADATA, {"skills/b/SKILL.md": "body\n"}
    )


def test_plugin_version_is_exact_only_for_the_recorded_release_content():
    assert claude_plugin_version("1.2.3", _DIGEST, _release()) == "1.2.3"
    other = "sha256:" + "0c" * 32
    assert claude_plugin_version("1.2.3", other, _release()) == (
        "1.2.4-dev.sha256-0c0c0c0c0c0c"
    )
    # nothing recorded, or a record for another version, is never the release
    assert claude_plugin_version("1.2.3", _DIGEST, _release(digest=None)) == (
        "1.2.4-dev.sha256-abababababab"
    )
    assert claude_plugin_version("1.2.3", _DIGEST, _release("1.2.2")).startswith(
        "1.2.4-dev."
    )
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        claude_plugin_version("1.2", other, _release())


def test_parse_plugin_release_accepts_only_the_exact_shape():
    assert parse_plugin_release(_release()) == _release()
    assert parse_plugin_release(_release(digest=None))["content_sha256"] is None
    for bad in (
        [],
        {**_release(), "extra": 1},
        {**_release(), "schema_version": 2},
        _release(version="1.2"),
        _release(version="01.2.3"),
        _release(digest="sha256:abc"),
        _release(digest=1),
    ):
        with pytest.raises(ValueError):
            parse_plugin_release(bad)


# --- provenance --verify (#109) ---------------------------------------------


@pytest.fixture
def installed_skills(tmp_path, monkeypatch):
    """A copy of the bundled skills that ``provenance --verify`` re-hashes."""
    copy = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILLS_DIR, copy)
    monkeypatch.setattr(provenance, "DEFAULT_SKILLS_DIR", copy)
    return copy


def test_verify_bundled_skills_accepts_the_installed_skills(installed_skills):
    assert verify_bundled_skills() == []


def test_verify_bundled_skills_reports_every_kind_of_drift(installed_skills):
    body = installed_skills / "logging" / "skill.md"
    body.write_text(body.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
    (installed_skills / "code-smells" / "notes.md").write_text("x", encoding="utf-8")
    shutil.rmtree(installed_skills / "iac-review")
    (installed_skills / "rogue").mkdir()
    problems = verify_bundled_skills()
    assert any(p.startswith("logging: installed files do not match") for p in problems)
    assert "code-smells: unexpected file(s): notes.md" in problems
    assert any(p.startswith("iac-review: cannot read") for p in problems)
    assert "rogue: not listed in the packaged content manifest" in problems
    assert len(problems) == 4


def test_verify_bundled_skills_uses_newline_normalised_identity(installed_skills):
    meta = installed_skills / "logging" / "meta.yaml"
    meta.write_bytes(meta.read_bytes().replace(b"\n", b"\r\n"))
    assert verify_bundled_skills() == []


def test_provenance_verify_passes_and_says_so(installed_skills):
    result = CliRunner().invoke(cli, ["provenance", "--verify"])
    assert result.exit_code == 0, result.output
    assert "verified: " in result.output

    plain = CliRunner().invoke(cli, ["provenance", "--json"])
    checked = CliRunner().invoke(cli, ["provenance", "--verify", "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output) == json.loads(plain.output)


def test_provenance_verify_fails_on_a_modified_install(installed_skills):
    body = installed_skills / "security-review" / "skill.md"
    body.write_text("# replaced\n", encoding="utf-8")
    # the embedded claim alone still reports the original identity...
    claim = CliRunner().invoke(cli, ["provenance"])
    assert claim.exit_code == 0
    # ...which --verify refuses once it re-hashes the installed files
    result = CliRunner().invoke(cli, ["provenance", "--verify", "--json"])
    assert result.exit_code == 1
    assert "error: security-review: installed files do not match" in result.output
    assert "do not match the content manifest" in result.output
    assert '"distribution"' not in result.output


def test_provenance_reports_a_broken_packaged_manifest_cleanly(monkeypatch):
    def broken():
        raise ValueError("invalid packaged provenance resource: x")

    monkeypatch.setattr("skilldeck.cli.distribution_provenance", broken)
    result = CliRunner().invoke(cli, ["provenance", "--verify"])
    assert result.exit_code == 1
    assert "invalid packaged provenance resource" in result.output
