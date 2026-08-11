from pathlib import Path

import pytest

from skilldeck.provenance import (
    canonical_skill_digest,
    content_manifest,
    normalise_text,
    sha256_text,
)
from skilldeck.registry import Skill


def _skill(tmp_path: Path, name: str) -> Skill:
    root = tmp_path / name
    root.mkdir()
    (root / "meta.yaml").write_text(
        f"name: {name}\ndescription: Example\ncategory: review\n"
        "version: 1.2.3\nsupported-agents:\n  - claude\n"
    )
    body = f"# {name}\n\nReview carefully.\n"
    (root / "skill.md").write_text(body)
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
