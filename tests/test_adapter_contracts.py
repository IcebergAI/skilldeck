"""Adapter contract tests (#79).

``tests/fixtures/adapter-contracts/`` pins, for every adapter, the exact bytes
that installing one synthetic skill writes (stamp included), where they go at
each scope, and what the environment variables that move an agent's config
directory do to that. ``docs/compatibility.md`` publishes the compatibility
matrix these contracts back and embeds a digest of the fixtures, so a format or
location change can't land without updating the fixtures, the matrix and the
changelog together.

After an intended format change, regenerate the expected files with
``SKILLDECK_UPDATE_CONTRACTS=1 uv run --locked --extra dev pytest
tests/test_adapter_contracts.py``, review the fixture diff, then copy the new
digest the digest test reports into the matrix and the changelog.

These tests also check the matrix's path, "Moved by" and scope-error text
against the contracts. Status, minimum versions, the date checked and the
per-agent notes are maintained by hand.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path

import pytest
import yaml

from skilldeck.adapters import ADAPTERS, ALL_ADAPTERS, InstallState
from skilldeck.registry import SkillError, load_skill
from skilldeck.stamp import parse as parse_stamp
from skilldeck.targets import Scope

_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = _ROOT / "tests" / "fixtures" / "adapter-contracts"
MATRIX = _ROOT / "docs" / "compatibility.md"
CHANGELOG = _ROOT / "CHANGELOG.md"

#: set to 1 to rewrite the expected files from the current adapters
_UPDATE = os.environ.get("SKILLDECK_UPDATE_CONTRACTS") == "1"

CONTRACTS = json.loads((FIXTURES / "contracts.json").read_text(encoding="utf-8"))
SKILL = load_skill(FIXTURES / "skill" / CONTRACTS["skill"], known_agents=ADAPTERS)

#: the files a skill directory holds (``registry.load_skill``)
SKILL_FILES = ("meta.yaml", "skill.md")

#: (adapter, variable, case) for every environment case in the contracts
ENV_CASES = [
    (name, var, case)
    for name, contract in sorted(CONTRACTS["adapters"].items())
    for var, cases in sorted(contract["env"].items())
    for case in sorted(cases)
]


def expected_fixture_files(root: Path = FIXTURES) -> list[str]:
    """Every file the contracts in ``root`` call for, as sorted POSIX paths:
    ``contracts.json``, the synthetic skill's files, and each adapter's
    expected rendered file."""
    contracts = json.loads((root / "contracts.json").read_text(encoding="utf-8"))
    files = {"contracts.json"}
    files.update(f"skill/{contracts['skill']}/{name}" for name in SKILL_FILES)
    files.update(
        f"{name}/{Path(contract['project']).name}"
        for name, contract in contracts["adapters"].items()
    )
    return sorted(files)


def _canonical(rel: str, data: bytes) -> bytes:
    """The bytes of fixture ``rel`` that the contract digest covers.

    ``contracts.json`` counts as its canonical JSON without the ``_about``
    notes, so rewording those, or reformatting the file, is not a contract
    change.
    """
    if rel != "contracts.json":
        return data
    contracts = json.loads(data.decode("utf-8"))
    contracts.pop("_about", None)
    canonical = json.dumps(
        contracts, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return canonical.encode("utf-8")


def contract_digest(root: Path = FIXTURES) -> str:
    """sha256 over the contract's fixture files: each one's POSIX relative
    path and its bytes (see :func:`_canonical`)."""
    digest = hashlib.sha256()
    for rel in expected_fixture_files(root):
        data = _canonical(rel, (root / rel).read_bytes())
        digest.update(f"{rel}\0{len(data)}\0".encode())
        digest.update(data)
    return digest.hexdigest()


def changelog_records(text: str, mention: str) -> bool:
    """Whether ``mention`` is in the changelog's ``[Unreleased]`` section or
    its newest dated section.

    A contract change is recorded under ``[Unreleased]``. Cutting a release
    (``scripts/prepare_release.py``) moves that entry into a new dated
    section and leaves ``[Unreleased]`` empty, so the newest dated section
    counts too; an older one doesn't.
    """
    sections = re.split(r"^(?=## \[)", text, flags=re.MULTILINE)
    unreleased = [s for s in sections if s.startswith("## [Unreleased]")]
    dated = [s for s in sections if re.match(r"## \[\d", s)]
    candidates = unreleased[:1] + dated[:1]
    return any(mention in section for section in candidates)


def _expected_file(name: str) -> Path:
    """The fixture holding ``name``'s rendered file, byte for byte."""
    return FIXTURES / name / Path(CONTRACTS["adapters"][name]["project"]).name


def _check_bytes(name: str, dest: Path) -> None:
    expected = _expected_file(name)
    actual = dest.read_bytes()
    if _UPDATE:
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(actual)
    assert actual == expected.read_bytes(), (
        f"{name} renders {CONTRACTS['skill']} differently from its contract "
        f"({expected.relative_to(_ROOT).as_posix()}). If the format change is "
        "intended, regenerate the fixtures (see this module's docstring) and "
        "update docs/compatibility.md and CHANGELOG.md"
    )


def _frontmatter(text: str) -> object:
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n")[1])


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def test_every_adapter_has_a_contract():
    assert set(CONTRACTS["adapters"]) == set(ALL_ADAPTERS), (
        "add (or remove) the adapter's entry in "
        "tests/fixtures/adapter-contracts/contracts.json and its row in "
        "docs/compatibility.md"
    )


def test_fixture_directory_holds_exactly_the_contract_files():
    # A stray file would otherwise sit there unchecked, and an expected file
    # left behind by a renamed one would look like part of the contract.
    actual = {
        path.relative_to(FIXTURES).as_posix()
        for path in FIXTURES.rglob("*")
        if not path.is_dir()
    }
    expected = set(expected_fixture_files())
    assert actual == expected, (
        "tests/fixtures/adapter-contracts/ must hold exactly the contract's "
        f"files; unexpected: {sorted(actual - expected)}, "
        f"missing: {sorted(expected - actual)}"
    )


def test_fixtures_have_lf_line_endings():
    # The byte comparisons need the fixtures exactly as committed; a checkout
    # that converts them to CRLF (core.autocrlf on Windows) breaks them.
    # .gitattributes marks the directory -text to prevent that.
    crlf = [
        rel
        for rel in expected_fixture_files()
        if b"\r" in (FIXTURES / rel).read_bytes()
    ]
    assert not crlf, f"fixtures were checked out with CRLF line endings: {crlf}"


@pytest.mark.parametrize("name", sorted(ALL_ADAPTERS))
def test_project_install_matches_the_contract(name, tmp_path):
    contract = CONTRACTS["adapters"][name]
    adapter = ALL_ADAPTERS[name]
    project = tmp_path.resolve()
    dest = adapter.install(SKILL, Scope.PROJECT, project_root=project)
    assert dest.relative_to(project).as_posix() == contract["project"]
    assert adapter.relative_path(SKILL).as_posix() == contract["project"]
    _check_bytes(name, dest)

    text = dest.read_text(encoding="utf-8")
    found = parse_stamp(text)
    assert found is not None
    assert (found.name, found.version, found.modified) == (
        SKILL.name,
        SKILL.version,
        False,
    )
    assert adapter.inspect(SKILL, Scope.PROJECT, project)[0] is InstallState.CURRENT
    assert _frontmatter(text) == contract["frontmatter"]
    if adapter.creates_skill_dir:
        # Agent Skills: the frontmatter name must match the skill's folder
        assert contract["frontmatter"]["name"] == dest.parent.name


@pytest.mark.parametrize("name", sorted(ALL_ADAPTERS))
def test_global_install_matches_the_contract(name, tmp_path, home):
    contract = CONTRACTS["adapters"][name]
    adapter = ALL_ADAPTERS[name]
    if contract["global"] is None:
        assert adapter.scopes == (Scope.PROJECT,)
        # actionable: names what to use instead. Only an install is pointed
        # at another adapter, which would write different files.
        with pytest.raises(SkillError) as excinfo:
            adapter.install(SKILL, Scope.GLOBAL)
        for text in contract["global_error"]["install"]:
            assert text in str(excinfo.value)
        with pytest.raises(SkillError) as excinfo:
            adapter.check_scope(Scope.GLOBAL)
        for text in contract["global_error"]["other"]:
            assert text in str(excinfo.value)
        assert "--agent" not in str(excinfo.value)
        assert not home.exists()
        return
    assert contract["global"].startswith("~/")
    dest = adapter.install(SKILL, Scope.GLOBAL)
    assert "~/" + dest.relative_to(home).as_posix() == contract["global"]
    _check_bytes(name, dest)


def test_env_contract_covers_every_variable_an_adapter_reads():
    for name, adapter in ALL_ADAPTERS.items():
        var = adapter.global_dir.env if adapter.global_dir else None
        declared = set(CONTRACTS["adapters"][name]["env"])
        if var is not None:
            assert var in declared, f"{name} reads {var}; add it to its contract"
            assert {"absolute", "empty", "relative"} <= set(
                CONTRACTS["adapters"][name]["env"][var]
            )


@pytest.mark.parametrize("name,var,case", ENV_CASES)
def test_env_overrides_match_the_contract(name, var, case, tmp_path, home, monkeypatch):
    adapter = ALL_ADAPTERS[name]
    moved = tmp_path / "moved-config"
    value = {"absolute": str(moved), "empty": "", "relative": "relative/dir"}[case]
    monkeypatch.setenv(var, value)
    expected = CONTRACTS["adapters"][name]["env"][var][case]
    if expected == "error":
        with pytest.raises(SkillError, match=var):
            adapter.install(SKILL, Scope.GLOBAL)
        return
    dest = adapter.install(SKILL, Scope.GLOBAL)
    if expected.startswith(f"${var}/"):
        assert dest.relative_to(moved).as_posix() == expected[len(var) + 2 :]
    else:
        assert "~/" + dest.relative_to(home).as_posix() == expected
    _check_bytes(name, dest)


#: the matrix's columns, in order
MATRIX_COLUMNS = (
    "adapter",
    "status",
    "project",
    "global",
    "moved by",
    "minimum version",
    "last checked",
)


def _matrix_row(name: str) -> dict[str, str]:
    rows = [
        line
        for line in MATRIX.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| `{name}` |")
    ]
    assert len(rows) == 1, f"docs/compatibility.md needs one matrix row for {name}"
    cells = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
    assert len(cells) == len(MATRIX_COLUMNS), rows[0]
    return dict(zip(MATRIX_COLUMNS, cells, strict=True))


@pytest.mark.parametrize("name", sorted(ALL_ADAPTERS))
def test_matrix_row_matches_the_contract(name):
    contract = CONTRACTS["adapters"][name]
    row = _matrix_row(name)
    assert row["status"] in ("tested", "supported", "experimental")

    def shown(path: str) -> str:
        return f"`{path.replace(CONTRACTS['skill'], '<name>')}`"

    assert row["project"] == shown(contract["project"])
    if contract["global"] is None:
        assert row["global"] == "not supported"
        assert row["moved by"] == "n/a"
        return
    assert row["global"] == shown(contract["global"])

    # "Moved by" names exactly the variables that move the global install,
    # each with where it moves it, and mentions any that don't
    entry = ALL_ADAPTERS[name].entry(SKILL).as_posix()
    moving = {}
    for var, cases in contract["env"].items():
        if cases["absolute"].startswith(f"${var}/"):
            moving[var] = cases["absolute"].removesuffix(f"/{entry}")
        else:
            assert f"`{var}`" in row["moved by"], f"say that {var} doesn't move it"
    named = set(re.findall(r"`\$([A-Z][A-Z0-9_]*)[/`]", row["moved by"]))
    assert named == set(moving)
    for var, target in moving.items():
        assert row["moved by"].startswith(f"`{var}`, to `{target}`")
    if not moving:
        assert row["moved by"].startswith("nothing")


def test_matrix_scope_error_example_is_current():
    # docs/compatibility.md quotes the error for an unsupported scope
    messages = set()
    for adapter in ALL_ADAPTERS.values():
        if Scope.GLOBAL in adapter.scopes:
            continue
        for installing in (False, True):
            with pytest.raises(SkillError) as excinfo:
                adapter.check_scope(Scope.GLOBAL, installing=installing)
            messages.add(f"error: {excinfo.value}")
    quoted = [
        line
        for line in MATRIX.read_text(encoding="utf-8").splitlines()
        if line.startswith("error: ")
    ]
    assert quoted
    assert set(quoted) <= messages


def test_matrix_and_changelog_record_the_contract_digest():
    digest = contract_digest()
    line = f"<!-- adapter-contract: sha256:{digest} -->"
    assert line in MATRIX.read_text(encoding="utf-8"), (
        "the adapter contract fixtures changed: an adapter's output format or "
        "location is different. Update the affected rows of "
        "docs/compatibility.md (status, paths, verification date), replace its "
        f"adapter-contract line with\n{line}\nand record the change in "
        f"CHANGELOG.md under [Unreleased], mentioning `sha256:{digest[:12]}`"
    )
    mention = f"sha256:{digest[:12]}"
    assert changelog_records(CHANGELOG.read_text(encoding="utf-8"), mention), (
        "record the adapter contract change in CHANGELOG.md under "
        f"[Unreleased], mentioning `{mention}`"
    )


def test_contract_notes_are_not_part_of_the_digest(tmp_path):
    copy = tmp_path / "contracts"
    shutil.copytree(FIXTURES, copy)
    path = copy / "contracts.json"
    contracts = json.loads(path.read_text(encoding="utf-8"))
    contracts["_about"] = ["reworded"]
    path.write_text(json.dumps(contracts, indent=4), encoding="utf-8")
    assert contract_digest(copy) == contract_digest()
    contracts["adapters"]["claude"]["frontmatter"]["name"] = "changed"
    path.write_text(json.dumps(contracts), encoding="utf-8")
    assert contract_digest(copy) != contract_digest()


def test_digest_covers_only_the_contract_files(tmp_path):
    copy = tmp_path / "contracts"
    shutil.copytree(FIXTURES, copy)
    (copy / "stray.txt").write_text("x", encoding="utf-8")
    assert contract_digest(copy) == contract_digest()
    with (copy / "kiro" / "SKILL.md").open("ab") as handle:
        handle.write(b"x")
    assert contract_digest(copy) != contract_digest()


_CHANGELOG = """# Changelog

## [Unreleased]
{unreleased}
## [0.4.0] - 2026-10-01

### Added

- {newest}

## [0.3.0] - 2026-06-27

- {older}
"""


@pytest.mark.parametrize(
    "where,recorded",
    [
        ({"unreleased": "\n### Added\n\n- contract sha256:abcdef012345\n"}, True),
        ({"newest": "contract sha256:abcdef012345"}, True),  # just released
        ({"older": "contract sha256:abcdef012345"}, False),
        ({}, False),
    ],
)
def test_changelog_records_the_digest_before_and_after_a_release(where, recorded):
    text = _CHANGELOG.format(
        **{"unreleased": "", "newest": "other", "older": "other", **where}
    )
    assert changelog_records(text, "sha256:abcdef012345") is recorded


def test_cutting_a_release_keeps_the_digest_recorded():
    # the real changelog, through the real release-prep step
    spec = importlib.util.spec_from_file_location(
        "prepare_release", _ROOT / "scripts" / "prepare_release.py"
    )
    assert spec and spec.loader
    prepare_release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare_release)
    mention = f"sha256:{contract_digest()[:12]}"
    text = CHANGELOG.read_text(encoding="utf-8")
    released = prepare_release.cut_changelog(text, "99.0.0", "2099-01-01")
    unreleased = released.split("## [Unreleased]")[1].split("## [")[0]
    assert mention not in unreleased
    assert changelog_records(released, mention)
