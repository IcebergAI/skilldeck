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


def test_non_mapping_meta_rejected(tmp_path):
    # A meta.yaml that parses to a scalar must fail with SkillError, not a
    # TypeError from indexing into a string (``"name" in meta`` is a substring
    # check when meta is a str, so field validation alone doesn't catch this).
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "meta.yaml").write_text(
        "name description category version supported-agents"
    )
    (skill_dir / "skill.md").write_text("body")
    with pytest.raises(SkillError, match="must be a YAML mapping"):
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


def _write_meta(root, name="demo", **overrides):
    """Write a skill whose meta.yaml fields are raw YAML, overridable per test."""
    fields = {
        "name": name,
        "description": "a test skill",
        "category": "testing",
        "version": "0.1.0",
        "supported-agents": "[claude]",
        **overrides,
    }
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "meta.yaml").write_text(
        "".join(f"{key}: {value}\n" for key, value in fields.items())
    )
    (skill_dir / "skill.md").write_text("body")
    return skill_dir


def test_bundled_skills_pass_validation():
    from skilldeck.adapters import ADAPTERS

    skills = discover_skills(known_agents=set(ADAPTERS))
    assert skills
    assert all(isinstance(skill.version, str) for skill in skills)


@pytest.mark.parametrize("raw", ["1.10", "1", "2.0", "true"])
def test_unquoted_numeric_version_is_rejected_with_a_hint(tmp_path, raw):
    # #97: YAML reads ``version: 1.10`` as the float 1.1; stringifying it would
    # record the wrong version, so the author is told to quote it instead.
    skill_dir = _write_meta(tmp_path, version=raw)
    with pytest.raises(SkillError, match="version must be a string.*quote it"):
        load_skill(skill_dir)


@pytest.mark.parametrize("raw", ['"1.10"', '"v1.0.0"', '"1.0.0-rc1"', '"01.0.0"'])
def test_version_must_be_major_minor_patch(tmp_path, raw):
    skill_dir = _write_meta(tmp_path, version=raw)
    with pytest.raises(SkillError, match="MAJOR.MINOR.PATCH"):
        load_skill(skill_dir)


@pytest.mark.parametrize("raw", ['"1.10.0"', "0.1.0", "'10.0.3'"])
def test_valid_versions_are_kept_verbatim(tmp_path, raw):
    skill = load_skill(_write_meta(tmp_path, version=raw))
    assert skill.version == raw.strip("\"'")


@pytest.mark.parametrize(
    "field,raw",
    [
        ("name", "123"),
        ("name", "''"),
        ("description", "[a, b]"),
        ("description", "{a: b}"),
        ("description", "''"),
        ("description", "'   '"),
        ("description", "42"),
        ("category", "[security]"),
        ("category", "''"),
        ("category", "null"),
    ],
)
def test_text_fields_must_be_non_empty_strings(tmp_path, field, raw):
    skill_dir = _write_meta(tmp_path, **{field: raw})
    with pytest.raises(SkillError, match=f"{field} must be a non-empty string"):
        load_skill(skill_dir)


@pytest.mark.parametrize(
    "name",
    ["Demo", "-demo", "demo-", "de--mo", "de_mo", "de.mo", "a" * 65],
)
def test_name_must_be_a_short_slug(tmp_path, name):
    # Agent Skills spec: 1-64 of [a-z0-9-], no leading/trailing/double hyphen.
    # Adapters also build file paths from the name.
    skill_dir = _write_meta(tmp_path, name=name)
    with pytest.raises(SkillError, match="lowercase letters, digits"):
        load_skill(skill_dir)


def test_name_at_the_length_limit_is_accepted(tmp_path):
    name = "a" * 64
    assert load_skill(_write_meta(tmp_path, name=name)).name == name


def test_description_must_be_a_single_line(tmp_path):
    skill_dir = _write_meta(tmp_path, description="|\n  line one\n  line two")
    with pytest.raises(SkillError, match="single line"):
        load_skill(skill_dir)


@pytest.mark.parametrize(
    "escape", ["\\n", "\\r", "\\x0b", "\\x0c", "\\x85", "\\u2028", "\\u2029"]
)
def test_description_rejects_every_line_break(tmp_path, escape):
    # A double-quoted YAML escape can smuggle in any line boundary that
    # str.splitlines() (and so the one-line `skilldeck list`) honours.
    skill_dir = _write_meta(tmp_path, description=f'"one{escape}two"')
    with pytest.raises(SkillError, match="single line"):
        load_skill(skill_dir)


@pytest.mark.parametrize("filename", ["meta.yaml", "skill.md"])
def test_non_utf8_skill_files_are_a_clean_error(tmp_path, filename):
    skill_dir = _write_meta(tmp_path)
    path = skill_dir / filename
    path.write_bytes(path.read_bytes() + b"\xe9\n")
    with pytest.raises(SkillError, match=f"{filename} is not valid UTF-8"):
        load_skill(skill_dir)


def test_description_length_is_capped(tmp_path):
    assert load_skill(_write_meta(tmp_path, description="x" * 1024))
    skill_dir = _write_meta(tmp_path, name="other", description="x" * 1025)
    with pytest.raises(SkillError, match="1025 characters; the limit is 1024"):
        load_skill(skill_dir)


def test_supported_agents_must_be_strings(tmp_path):
    skill_dir = _write_meta(tmp_path, **{"supported-agents": "[claude, 3]"})
    with pytest.raises(SkillError, match="entries must be strings"):
        load_skill(skill_dir)


def test_supported_agents_must_be_a_list(tmp_path):
    skill_dir = _write_meta(tmp_path, **{"supported-agents": "claude"})
    with pytest.raises(SkillError, match="non-empty list"):
        load_skill(skill_dir)


def test_duplicate_supported_agents_rejected(tmp_path):
    skill_dir = _write_meta(tmp_path, **{"supported-agents": "[claude, codex, claude]"})
    with pytest.raises(SkillError, match="more than once: claude"):
        load_skill(skill_dir)


def test_invalid_yaml_is_a_clean_error(tmp_path):
    skill_dir = _write_meta(tmp_path)
    (skill_dir / "meta.yaml").write_text("name: [unclosed\n")
    with pytest.raises(SkillError, match="not valid YAML"):
        load_skill(skill_dir)
