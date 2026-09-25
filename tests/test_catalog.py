"""``skilldeck catalog`` (#77): the schema-versioned, machine-readable catalog."""

import json
import re
import shutil
import textwrap

import pytest
from click.testing import CliRunner

from _schema import SUPPORTED_KEYWORDS, catalog_schema, schema_errors, schema_nodes
from skilldeck import __version__, catalog, provenance, registry
from skilldeck.adapters import ADAPTERS
from skilldeck.catalog import (
    CATALOG_SCHEMA_VERSION,
    CatalogError,
    build_catalog,
)
from skilldeck.cli import cli
from skilldeck.provenance import (
    canonical_json,
    content_manifest,
    load_content_manifest,
)
from skilldeck.registry import DEFAULT_SKILLS_DIR, discover_skills
from skilldeck.targets import Scope


def test_schema_uses_only_supported_keywords():
    for node in schema_nodes(catalog_schema()):
        assert set(node) <= SUPPORTED_KEYWORDS, set(node) - SUPPORTED_KEYWORDS
        if "$ref" in node:  # schema_errors merges a $ref's siblings into it
            assert set(node) <= {"$ref", "description"}


def test_schema_requires_every_property_it_describes():
    # additive fields may be optional to consumers, but skilldeck always
    # emits every field (null when empty), so the schema requires them all
    # (oneOf branches only add constraints to properties required above them)
    for node in schema_nodes(catalog_schema(), branches=False):
        if "properties" in node:
            assert set(node["required"]) == set(node["properties"])


def test_schema_version_matches_the_code():
    schema = catalog_schema()
    assert schema["properties"]["schema_version"]["const"] == CATALOG_SCHEMA_VERSION
    assert f"schema_version {CATALOG_SCHEMA_VERSION}" in schema["title"]


def test_validator_rejects_malformed_catalogs():
    good = json.loads(_invoke("catalog", "--json").stdout)
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
    assert broken(
        lambda d: d["skills"][0]["rendered_sha256"].update(claude="sha256:abc")
    )
    # a tag without its commit, or a commit without its tag
    commit = "0" * 40
    assert broken(lambda d: d["distribution"].update(source_ref="refs/tags/v1.0.0"))
    assert broken(lambda d: d["distribution"].update(source_commit=commit))
    assert not broken(
        lambda d: d["distribution"].update(
            source_ref="refs/tags/v1.0.0", source_commit=commit
        )
    )
    # consumers must ignore unknown properties, so the schema allows them
    assert not broken(lambda d: d["skills"][0].update(added_later=1))

    def caps(change):
        return broken(lambda d: change(d["skills"][0]["capabilities"]))

    assert broken(lambda d: d["skills"][0].pop("capabilities"))
    assert caps(lambda c: c.update(schema=2))
    assert caps(lambda c: c.pop("network"))
    assert caps(lambda c: c["files"].update(read="everything"))
    assert caps(lambda c: c["files"].update(write="diff"))
    assert caps(lambda c: c.update(commands=["git diff", "git diff"]))
    assert caps(lambda c: c.update(tools=[""]))
    for path in ("../x.md", "a/../b.md", "/etc/x", "./x", "a//b", "a\\b", "..", "."):
        assert caps(lambda c, path=path: c.update(artifacts=[path])), path
    assert not caps(lambda c: c.update(artifacts=["reports/review.md", ".x/y"]))


# --- the command --------------------------------------------------------------


def _runner():
    # Click < 8.2 mixes stderr into stdout unless told not to; 8.2 dropped the
    # flag and always captures the streams separately
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def _invoke(*args):
    result = _runner().invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    return result


def test_catalog_json_is_deterministic_canonical_json():
    first = _invoke("catalog", "--json").stdout_bytes
    second = _invoke("catalog", "--json").stdout_bytes
    assert first == second
    # sorted keys, fixed indentation, ASCII only, one final newline, and
    # written as bytes: no CRLF even on Windows
    assert first == canonical_json(json.loads(first)).encode("utf-8")
    assert first.isascii()
    assert b"\r" not in first


def test_provenance_json_is_written_as_the_same_canonical_bytes():
    out = _invoke("provenance", "--json").stdout_bytes
    assert out == canonical_json(json.loads(out)).encode("utf-8")
    assert b"\r" not in out


def test_catalog_lists_every_bundled_skill_exactly_once_sorted():
    data = json.loads(_invoke("catalog", "--json").stdout)
    assert data["schema_version"] == CATALOG_SCHEMA_VERSION
    names = [skill["name"] for skill in data["skills"]]
    assert names == sorted(skill.name for skill in discover_skills())
    assert len(names) == len(set(names))


def test_catalog_mirrors_canonical_metadata():
    data = json.loads(_invoke("catalog", "--json").stdout)
    by_name = {skill.name: skill for skill in discover_skills()}
    for entry in data["skills"]:
        skill = by_name[entry["name"]]
        assert entry["version"] == skill.version
        assert entry["category"] == skill.category
        assert entry["description"] == skill.description
        assert entry["supported_agents"] == sorted(skill.supported_agents)
        assert entry["deprecated"] is None
        assert entry["capabilities"] == skill.capabilities.record()
        assert entry["capabilities"]["schema"] == 1
        assert entry["source"] == {
            "repository": "https://github.com/IcebergAI/skilldeck",
            "path": f"src/skilldeck/skills/{skill.name}",
        }


def test_catalog_digests_are_the_ones_provenance_verifies():
    data = json.loads(_invoke("catalog", "--json").stdout)
    recorded = {
        record["name"]: record["canonical_sha256"]
        for record in load_content_manifest()["skills"]
    }
    provenance = json.loads(_invoke("provenance", "--verify", "--json").stdout)
    verified = {s["name"]: s["canonical_sha256"] for s in provenance["skills"]}
    digests = {s["name"]: s["canonical_sha256"] for s in data["skills"]}
    assert digests == recorded == verified
    assert data["distribution"] == provenance["distribution"]


def test_rendered_digests_match_install_stamps(tmp_path, monkeypatch):
    # what a stamp's hash= records, for every native agent, is in the catalog
    monkeypatch.chdir(tmp_path)
    _invoke("install", "--all", "--agent", "all")
    data = json.loads(_invoke("catalog", "--json").stdout)
    by_name = {skill.name: skill for skill in discover_skills()}
    compared = 0
    for entry in data["skills"]:
        skill = by_name[entry["name"]]
        assert sorted(entry["rendered_sha256"]) == entry["supported_agents"]
        for agent, digest in entry["rendered_sha256"].items():
            installed = ADAPTERS[agent].destination(skill, Scope.PROJECT)
            text = installed.read_text(encoding="utf-8")
            recorded = re.search(r" hash=([0-9a-f]{64}) -->\n\Z", text)
            assert recorded, installed
            assert digest == f"sha256:{recorded.group(1)}"
            compared += 1
    assert compared == sum(len(s.supported_agents) for s in by_name.values())


def test_catalog_output_validates_against_the_schema():
    data = json.loads(_invoke("catalog", "--json").stdout)
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
    data = json.loads(_invoke("catalog", "--json", *args).stdout)
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


def test_unknown_category_warns_with_the_known_ones():
    result = _invoke("catalog", "--json", "--category", "nope", "--category", "review")
    assert json.loads(result.stdout)["skills"]
    categories = ", ".join(sorted({s.category for s in discover_skills()}))
    assert result.stderr == (
        f"warning: no skill has category nope; the categories are {categories}\n"
    )
    assert _invoke("catalog", "--category", "review").stderr == ""


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
        capabilities:
          schema: 1
          files: {{read: repo, write: none}}
          commands: [git diff]
          network: []
          credentials: []
          tools: []
          artifacts: []
        """
    )
    (skill_dir / "meta.yaml").write_text(meta + extra, encoding="utf-8")
    (skill_dir / "skill.md").write_text(f"# {name}\n", encoding="utf-8")


def _use(monkeypatch, root, manifest=None):
    """Point skilldeck at ``root`` and a content manifest recorded for it."""
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", root)
    monkeypatch.setattr(provenance, "DEFAULT_SKILLS_DIR", root)
    if manifest is None:
        manifest = content_manifest(__version__, discover_skills(root))
    monkeypatch.setattr(provenance, "load_content_manifest", lambda: manifest)
    monkeypatch.setattr(catalog, "load_content_manifest", lambda: manifest)


def _bundle_copy(tmp_path, monkeypatch):
    """A copy of the bundled skills, checked against the packaged manifest."""
    copy = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILLS_DIR, copy)
    monkeypatch.setattr(registry, "DEFAULT_SKILLS_DIR", copy)
    monkeypatch.setattr(provenance, "DEFAULT_SKILLS_DIR", copy)
    return copy


def _fails(*args):
    result = _runner().invoke(cli, list(args))
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "do not match the content manifest" in result.stderr
    return result.stderr


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
    data = json.loads(_invoke("catalog", "--json").stdout)
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


def test_show_summary_reports_deprecation(deprecated_skills):
    lines = _invoke("show", "old-review", "--summary").stdout.splitlines()
    assert (
        "  deprecated:  deprecated since 1.1.0; use new-review "
        "(Folded into new-review.)"
    ) in lines
    assert "  deprecated:  no" in _invoke("show", "new-review", "--summary").stdout


def test_show_summary_names_the_release_it_was_built_from(monkeypatch):
    commit = "0123456789abcdef0123456789abcdef01234567"
    monkeypatch.setattr(
        "skilldeck.cli.load_build_metadata",
        lambda: {
            "schema_version": 1,
            "source_repository": "https://github.com/IcebergAI/skilldeck",
            "source_ref": "refs/tags/v9.9.9",
            "source_commit": commit,
        },
    )
    out = _invoke("show", "logging", "--summary").stdout
    assert (
        f"  built from:  refs/tags/v9.9.9, commit {commit} (recorded at build)\n" in out
    )
    monkeypatch.undo()
    out = _invoke("show", "logging", "--summary").stdout
    assert (
        "  built from:  a development build, with no release tag or commit "
        "(recorded at build)\n"
    ) in out


def test_list_does_not_mark_current_skills():
    assert "deprecated" not in _invoke("list").output


def test_catalog_rejects_skills_that_differ_from_the_manifest(tmp_path, monkeypatch):
    copy = _bundle_copy(tmp_path, monkeypatch)
    body = copy / "logging" / "skill.md"
    body.write_text(body.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
    shutil.rmtree(copy / "iac-review")
    errors = _fails("catalog", "--json")
    assert "error: logging: installed files do not match canonical digest" in errors
    assert "error: iac-review: cannot read the bundled skill" in errors


@pytest.mark.parametrize(
    ("extra", "problem"),
    [
        ("logging/payload.sh", "logging: unexpected file(s): payload.sh"),
        # an OS leftover loading ignores still fails the integrity check
        ("logging/.DS_Store", "logging: unexpected file(s): .DS_Store"),
        ("README.txt", "README.txt: not listed in the packaged content manifest"),
    ],
)
def test_catalog_rejects_files_the_manifest_does_not_list(
    tmp_path, monkeypatch, extra, problem
):
    # the skills themselves still match; provenance --verify fails, so must this
    copy = _bundle_copy(tmp_path, monkeypatch)
    (copy / extra).write_text("echo pwned\n", encoding="utf-8")
    assert f"error: {problem}" in _fails("catalog", "--json")
    assert CliRunner().invoke(cli, ["provenance", "--verify"]).exit_code == 1


def test_catalog_rejects_a_skill_missing_from_the_manifest(tmp_path, monkeypatch):
    root = _skills_dir(tmp_path)
    _write(root, "listed")
    manifest = content_manifest(__version__, discover_skills(root))
    _write(root, "unlisted")
    _use(monkeypatch, root, manifest)
    assert "error: unlisted: not listed in the" in _fails("catalog")


def test_build_catalog_checks_the_skills_it_is_given(tmp_path):
    # build_catalog also stands on its own, for callers other than the CLI
    root = _skills_dir(tmp_path)
    _write(root, "kept")
    _write(root, "dropped")
    manifest = content_manifest(__version__, discover_skills(root))
    (root / "kept" / "skill.md").write_text("changed\n", encoding="utf-8")
    skills = [s for s in discover_skills(root) if s.name == "kept"]
    with pytest.raises(CatalogError) as caught:
        build_catalog(skills, manifest)
    assert caught.value.problems == [
        f"kept: skill files do not match canonical digest "
        f"{manifest['skills'][1]['canonical_sha256']}",
        "dropped: listed in the content manifest but not bundled",
    ]


def test_catalog_digest_ignores_newline_style(tmp_path, monkeypatch):
    copy = _bundle_copy(tmp_path, monkeypatch)
    meta = copy / "logging" / "meta.yaml"
    # normalise first: a Windows checkout may already use CRLF
    lf = meta.read_bytes().replace(b"\r\n", b"\n")
    meta.write_bytes(lf.replace(b"\n", b"\r\n"))
    data = json.loads(_invoke("catalog", "--json").stdout)
    recorded = {
        record["name"]: record["canonical_sha256"]
        for record in load_content_manifest()["skills"]
    }
    assert {s["name"]: s["canonical_sha256"] for s in data["skills"]} == recorded


# --- install/update warn about deprecated skills --------------------------------


def test_install_warns_about_deprecated_skills(
    deprecated_skills, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = _invoke(
        "install",
        "old-review",
        "retired",
        "new-review",
        "--agent",
        "claude",
        "--agent",
        "codex",
    )
    assert result.stderr == (
        "warning: old-review is deprecated since 1.1.0; use new-review "
        "(Folded into new-review.)\n"
        "warning: retired is deprecated since 1.2.0 (Obsolete.)\n"
    )
    assert "installed old-review" in result.stdout


def test_update_warns_about_deprecated_skills(deprecated_skills, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _invoke("install", "--all", "--agent", "claude")
    meta = deprecated_skills / "retired" / "meta.yaml"
    meta.write_text(
        meta.read_text(encoding="utf-8").replace("version: 1.2.0", "version: 1.3.0"),
        encoding="utf-8",
    )
    result = _invoke("update", "--agent", "claude")
    assert "updated retired (1.2.0 -> 1.3.0)" in result.stdout
    assert result.stderr == "warning: retired is deprecated since 1.2.0 (Obsolete.)\n"
    # nothing refreshed, nothing to warn about
    assert _invoke("update", "--agent", "claude").stderr == ""
