"""``skilldeck catalog`` (#77): the schema-versioned, machine-readable catalog."""

import json
import re
import shutil
import textwrap

import pytest
from click.testing import CliRunner

from skilldeck import __version__, catalog, registry
from skilldeck.catalog import CATALOG_SCHEMA_VERSION, catalog_schema_text
from skilldeck.cli import cli
from skilldeck.provenance import (
    canonical_json,
    content_manifest,
    load_content_manifest,
)
from skilldeck.registry import DEFAULT_SKILLS_DIR, discover_skills

# --- a minimal JSON Schema validator ------------------------------------------
# Only the keywords the committed schema uses, so the tests need no new
# dependency; test_schema_uses_only_supported_keywords keeps it honest.

SUPPORTED_KEYWORDS = {
    "$schema",
    "title",
    "description",
    "$defs",
    "$ref",
    "type",
    "const",
    "required",
    "properties",
    "items",
    "pattern",
    "minLength",
    "maxLength",
    "minItems",
    "uniqueItems",
}
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def _schema():
    return json.loads(catalog_schema_text())


def schema_errors(instance, schema=None, *, exact=False):
    """Every way ``instance`` breaks ``schema``; with ``exact``, also any
    object property the schema does not describe."""
    root = schema or _schema()
    errors: list[str] = []

    def check(value, node, path):
        if "$ref" in node:
            # the schema's $ref siblings are only annotations, so merging the
            # target in is exact here (and lets ``exact`` see its properties)
            target = root["$defs"][node["$ref"].removeprefix("#/$defs/")]
            node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        if "type" in node:
            types = node["type"] if isinstance(node["type"], list) else [node["type"]]
            if not any(_TYPES[t](value) for t in types):
                errors.append(f"{path}: {value!r} is not of type {types}")
                return
        if "const" in node and (
            value != node["const"] or type(value) is not type(node["const"])
        ):
            errors.append(f"{path}: {value!r} is not {node['const']!r}")
        if isinstance(value, str):
            if len(value) < node.get("minLength", 0):
                errors.append(f"{path}: too short")
            if len(value) > node.get("maxLength", len(value)):
                errors.append(f"{path}: too long")
            if "pattern" in node and not re.search(node["pattern"], value):
                errors.append(f"{path}: {value!r} does not match {node['pattern']}")
        if isinstance(value, list):
            if len(value) < node.get("minItems", 0):
                errors.append(f"{path}: too few items")
            if node.get("uniqueItems") and len(set(map(json.dumps, value))) != len(
                value
            ):
                errors.append(f"{path}: items are not unique")
            if "items" in node:
                for index, item in enumerate(value):
                    check(item, node["items"], f"{path}[{index}]")
        if isinstance(value, dict):
            for key in node.get("required", []):
                if key not in value:
                    errors.append(f"{path}: missing {key}")
            properties = node.get("properties", {})
            for key, item in value.items():
                if key in properties:
                    check(item, properties[key], f"{path}.{key}")
                elif exact:
                    errors.append(f"{path}: undocumented property {key}")

    check(instance, root, "$")
    return errors


def _schema_nodes(node):
    yield node
    for key in ("properties", "$defs"):
        for child in node.get(key, {}).values():
            yield from _schema_nodes(child)
    if "items" in node:
        yield from _schema_nodes(node["items"])


def test_schema_uses_only_supported_keywords():
    for node in _schema_nodes(_schema()):
        assert set(node) <= SUPPORTED_KEYWORDS, set(node) - SUPPORTED_KEYWORDS
        if "$ref" in node:  # schema_errors merges a $ref's siblings into it
            assert set(node) <= {"$ref", "description"}


def test_schema_requires_every_property_it_describes():
    # additive fields may be optional to consumers, but skilldeck always
    # emits every field (null when empty), so the schema requires them all
    for node in _schema_nodes(_schema()):
        if "properties" in node:
            assert set(node["required"]) == set(node["properties"])


def test_schema_version_matches_the_code():
    schema = _schema()
    assert schema["properties"]["schema_version"]["const"] == CATALOG_SCHEMA_VERSION
    assert f"schema_version {CATALOG_SCHEMA_VERSION}" in schema["title"]


def test_validator_rejects_malformed_catalogs():
    good = json.loads(_invoke("catalog", "--json").output)
    assert schema_errors(good, exact=True) == []

    def broken(change):
        data = json.loads(json.dumps(good))
        change(data)
        return schema_errors(data)

    assert broken(lambda d: d.update(schema_version=2))
    assert broken(lambda d: d.update(schema_version=True))
    assert broken(lambda d: d.pop("distribution"))
    assert broken(lambda d: d["skills"][0].pop("canonical_sha256"))
    assert broken(lambda d: d["skills"][0].update(canonical_sha256="sha256:abc"))
    assert broken(lambda d: d["skills"][0].update(supported_agents=[]))
    assert broken(lambda d: d["skills"][0].update(supported_agents=["a", "a"]))
    assert broken(lambda d: d["skills"][0].update(version="1.0"))
    assert broken(lambda d: d["skills"][0].update(deprecated={"since": "0.1.0"}))
    assert broken(
        lambda d: d["skills"][0].update(
            deprecated={"since": "0.1.0", "replacement": "Bad", "reason": "x"}
        )
    )
    # consumers must ignore unknown properties, so the schema allows them
    assert not broken(lambda d: d["skills"][0].update(added_later=1))


# --- the command --------------------------------------------------------------


def _invoke(*args):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    return result


def test_catalog_json_is_deterministic_canonical_json():
    first = _invoke("catalog", "--json").output
    second = _invoke("catalog", "--json").output
    assert first == second
    # sorted keys, fixed indentation, ASCII only, one final newline
    assert first == canonical_json(json.loads(first))
    assert first.isascii()


def test_catalog_lists_every_bundled_skill_exactly_once_sorted():
    data = json.loads(_invoke("catalog", "--json").output)
    assert data["schema_version"] == CATALOG_SCHEMA_VERSION
    names = [skill["name"] for skill in data["skills"]]
    assert names == sorted(skill.name for skill in discover_skills())
    assert len(names) == len(set(names))


def test_catalog_mirrors_canonical_metadata():
    data = json.loads(_invoke("catalog", "--json").output)
    by_name = {skill.name: skill for skill in discover_skills()}
    for entry in data["skills"]:
        skill = by_name[entry["name"]]
        assert entry["version"] == skill.version
        assert entry["category"] == skill.category
        assert entry["description"] == skill.description
        assert entry["supported_agents"] == sorted(skill.supported_agents)
        assert entry["deprecated"] is None
        assert entry["source"] == {
            "repository": "https://github.com/IcebergAI/skilldeck",
            "path": f"src/skilldeck/skills/{skill.name}",
        }


def test_catalog_digests_are_the_ones_provenance_verifies():
    data = json.loads(_invoke("catalog", "--json").output)
    recorded = {
        record["name"]: record["canonical_sha256"]
        for record in load_content_manifest()["skills"]
    }
    provenance = json.loads(_invoke("provenance", "--verify", "--json").output)
    verified = {s["name"]: s["canonical_sha256"] for s in provenance["skills"]}
    digests = {s["name"]: s["canonical_sha256"] for s in data["skills"]}
    assert digests == recorded == verified
    assert data["distribution"] == provenance["distribution"]


def test_catalog_output_validates_against_the_schema():
    data = json.loads(_invoke("catalog", "--json").output)
    assert schema_errors(data, exact=True) == []


def test_schema_option_prints_the_packaged_schema():
    text = _invoke("catalog", "--schema").output
    assert text == (DEFAULT_SKILLS_DIR.parent / "catalog.schema.json").read_text(
        encoding="utf-8"
    )
    assert json.loads(text)["$schema"].startswith("https://json-schema.org/")


def test_schema_option_takes_no_other_options():
    result = CliRunner().invoke(cli, ["catalog", "--schema", "--json"])
    assert result.exit_code == 2
    assert "--schema takes no other options" in result.output


# --- filters ------------------------------------------------------------------


def _names(*args):
    data = json.loads(_invoke("catalog", "--json", *args).output)
    assert schema_errors(data, exact=True) == []
    return [skill["name"] for skill in data["skills"]]


def test_category_filter():
    skills = discover_skills()
    assert _names("--category", "review") == [
        s.name for s in skills if s.category == "review"
    ]
    # repeated: any of the categories
    assert _names("--category", "review", "--category", "security") == [
        s.name for s in skills if s.category in {"review", "security"}
    ]
    # an unknown category is an empty, still valid, catalog
    assert _names("--category", "no-such-category") == []


def test_agent_filter():
    skills = discover_skills()
    assert _names("--agent", "claude") == [
        s.name for s in skills if "claude" in s.supported_agents
    ]
    # repeated: every named agent
    assert _names("--agent", "claude", "--agent", "kiro") == [
        s.name for s in skills if {"claude", "kiro"} <= set(s.supported_agents)
    ]
    assert _names("--agent", "codex", "--category", "review") == [
        s.name
        for s in skills
        if "codex" in s.supported_agents and s.category == "review"
    ]


def test_agent_filter_excludes_skills_without_that_agent(tmp_path, monkeypatch):
    root = _skills_dir(tmp_path)
    _write(root, "claude-only", agents="[claude]")
    _write(root, "both", agents="[claude, codex]")
    _use(monkeypatch, root)
    assert _names("--agent", "codex") == ["both"]
    assert _names("--agent", "claude") == ["both", "claude-only"]


def test_agent_filter_rejects_an_unknown_agent():
    result = CliRunner().invoke(cli, ["catalog", "--json", "--agent", "bogus"])
    assert result.exit_code == 2
    # a legacy format is an install target, not a supported-agents value
    result = CliRunner().invoke(cli, ["catalog", "--agent", "copilot-prompt"])
    assert result.exit_code == 2


# --- deprecated skills and manifest drift, on a temporary skills directory ----


def _skills_dir(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    return root


def _write(root, name, *, agents="[claude, codex]", extra=""):
    skill_dir = root / name
    skill_dir.mkdir()
    meta = textwrap.dedent(
        f"""\
        name: {name}
        description: The {name} skill.
        category: testing
        version: 1.2.0
        supported-agents: {agents}
        """
    )
    (skill_dir / "meta.yaml").write_text(meta + extra, encoding="utf-8")
    (skill_dir / "skill.md").write_text(f"# {name}\n", encoding="utf-8")


def _use(monkeypatch, root, manifest=None):
    """Point skilldeck at ``root`` and a content manifest recorded for it."""
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", root)
    if manifest is None:
        manifest = content_manifest(__version__, discover_skills(root))
    monkeypatch.setattr(catalog, "load_content_manifest", lambda: manifest)


@pytest.fixture
def deprecated_skills(tmp_path, monkeypatch):
    root = _skills_dir(tmp_path)
    _write(root, "new-review")
    _write(
        root,
        "old-review",
        extra="deprecated:\n  since: 1.1.0\n  replacement: new-review\n"
        "  reason: Folded into new-review.\n",
    )
    _write(root, "retired", extra="deprecated: {since: 1.2.0, reason: Obsolete.}\n")
    _use(monkeypatch, root)
    return root


def test_catalog_reports_deprecation_state(deprecated_skills):
    data = json.loads(_invoke("catalog", "--json").output)
    assert schema_errors(data, exact=True) == []
    states = {skill["name"]: skill["deprecated"] for skill in data["skills"]}
    assert states == {
        "new-review": None,
        "old-review": {
            "since": "1.1.0",
            "replacement": "new-review",
            "reason": "Folded into new-review.",
        },
        "retired": {"since": "1.2.0", "replacement": None, "reason": "Obsolete."},
    }


def test_human_catalog_and_list_mark_deprecated_skills(deprecated_skills):
    for command in ("catalog", "list"):
        lines = {
            line.split()[0]: line
            for line in _invoke(command).output.splitlines()
            if line.strip()
        }
        assert lines["old-review"].endswith("(deprecated since 1.1.0; use new-review)")
        assert lines["retired"].endswith("(deprecated since 1.2.0)")
        assert "deprecated" not in lines["new-review"]


def test_list_does_not_mark_current_skills():
    assert "deprecated" not in _invoke("list").output


def test_catalog_rejects_skills_that_differ_from_the_manifest(tmp_path, monkeypatch):
    copy = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILLS_DIR, copy)
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", copy)
    body = copy / "logging" / "skill.md"
    body.write_text(body.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
    shutil.rmtree(copy / "iac-review")

    result = CliRunner().invoke(cli, ["catalog", "--json"])
    assert result.exit_code == 1
    assert "error: logging: skill files do not match canonical digest" in (
        result.output
    )
    assert (
        "error: iac-review: listed in the content manifest but not bundled"
        in result.output
    )
    assert "do not match the content manifest" in result.output
    assert not result.output.lstrip().startswith("{")


def test_catalog_rejects_a_skill_missing_from_the_manifest(tmp_path, monkeypatch):
    root = _skills_dir(tmp_path)
    _write(root, "listed")
    manifest = content_manifest(__version__, discover_skills(root))
    _write(root, "unlisted")
    _use(monkeypatch, root, manifest)
    result = CliRunner().invoke(cli, ["catalog"])
    assert result.exit_code == 1
    assert "error: unlisted: not listed in the content manifest" in result.output


def test_catalog_digest_ignores_newline_style(tmp_path, monkeypatch):
    copy = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILLS_DIR, copy)
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", copy)
    meta = copy / "logging" / "meta.yaml"
    # normalise first: a Windows checkout may already use CRLF
    lf = meta.read_bytes().replace(b"\r\n", b"\n")
    meta.write_bytes(lf.replace(b"\n", b"\r\n"))
    data = json.loads(_invoke("catalog", "--json").output)
    recorded = {
        record["name"]: record["canonical_sha256"]
        for record in load_content_manifest()["skills"]
    }
    assert {s["name"]: s["canonical_sha256"] for s in data["skills"]} == recorded
