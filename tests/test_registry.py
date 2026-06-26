import textwrap

import pytest

from skilldeck.registry import SkillError, discover_skills, load_skill


def _write_skill(root, name, *, agents="[claude, codex, kiro]", body="hi"):
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "meta.yaml").write_text(
        textwrap.dedent(
            f"""
            name: {name}
            description: a test skill
            category: testing
            version: 0.1.0
            supported-agents: {agents}
            """
        ).strip()
    )
    (skill_dir / "skill.md").write_text(body)
    return skill_dir


def test_load_skill_roundtrip(tmp_path):
    skill_dir = _write_skill(tmp_path, "demo", body="the body")
    skill = load_skill(skill_dir)
    assert skill.name == "demo"
    assert skill.supported_agents == ("claude", "codex", "kiro")
    assert skill.body == "the body"


def test_supported_agents_is_hashable(tmp_path):
    # frozen dataclass + tuple field -> usable in a set / as a dict key
    skill = load_skill(_write_skill(tmp_path, "demo"))
    assert {skill}  # would raise TypeError if supported_agents were a list


def test_unknown_agent_rejected_when_known_agents_given(tmp_path):
    skill_dir = _write_skill(tmp_path, "demo", agents="[claude, bogus]")
    with pytest.raises(SkillError, match="unknown agent"):
        load_skill(skill_dir, known_agents={"claude", "codex", "kiro"})


def test_name_must_match_directory(tmp_path):
    skill_dir = _write_skill(tmp_path, "demo")
    (skill_dir / "meta.yaml").write_text(
        "name: other\n"
        "description: x\n"
        "category: y\n"
        "version: 1\n"
        "supported-agents: [claude]\n"
    )
    with pytest.raises(SkillError, match="does not match"):
        load_skill(skill_dir)


def test_missing_field_raises(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "meta.yaml").write_text("name: demo\n")
    (skill_dir / "skill.md").write_text("body")
    with pytest.raises(SkillError, match="missing fields"):
        load_skill(skill_dir)


def test_empty_supported_agents_rejected(tmp_path):
    skill_dir = _write_skill(tmp_path, "demo", agents="[]")
    with pytest.raises(SkillError, match="non-empty list"):
        load_skill(skill_dir)


def test_missing_skill_md_rejected(tmp_path):
    skill_dir = _write_skill(tmp_path, "demo")
    (skill_dir / "skill.md").unlink()
    with pytest.raises(SkillError, match="missing skill.md"):
        load_skill(skill_dir)


def test_discover_missing_directory_rejected(tmp_path):
    with pytest.raises(SkillError, match="not found"):
        discover_skills(tmp_path / "does-not-exist")


def test_discover_sorted(tmp_path):
    _write_skill(tmp_path, "bravo")
    _write_skill(tmp_path, "alpha")
    names = [s.name for s in discover_skills(tmp_path)]
    assert names == ["alpha", "bravo"]
