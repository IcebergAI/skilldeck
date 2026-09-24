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
"""

import hashlib
import json
import os
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

#: (adapter, variable, case) for every environment case in the contracts
ENV_CASES = [
    (name, var, case)
    for name, contract in sorted(CONTRACTS["adapters"].items())
    for var, cases in sorted(contract["env"].items())
    for case in sorted(cases)
]


def _fixture_files() -> list[Path]:
    return sorted(
        (path for path in FIXTURES.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(FIXTURES).as_posix(),
    )


def contract_digest() -> str:
    """sha256 over every fixture file's POSIX relative path and exact bytes."""
    digest = hashlib.sha256()
    for path in _fixture_files():
        data = path.read_bytes()
        rel = path.relative_to(FIXTURES).as_posix()
        digest.update(f"{rel}\0{len(data)}\0".encode())
        digest.update(data)
    return digest.hexdigest()


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
    dirs = {path.name for path in FIXTURES.iterdir() if path.is_dir()}
    assert dirs - {"skill"} == set(ALL_ADAPTERS)


def test_fixtures_have_lf_line_endings():
    # The byte comparisons need the fixtures exactly as committed; a checkout
    # that converts them to CRLF (core.autocrlf on Windows) breaks them.
    # .gitattributes marks the directory -text to prevent that.
    crlf = [
        path.relative_to(FIXTURES).as_posix()
        for path in _fixture_files()
        if b"\r" in path.read_bytes()
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
        with pytest.raises(SkillError) as excinfo:
            adapter.install(SKILL, Scope.GLOBAL)
        message = str(excinfo.value)
        # actionable: names what to use instead
        for text in contract["global_error"]:
            assert text in message
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


def _matrix_row(name: str) -> str:
    rows = [
        line
        for line in MATRIX.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| `{name}` |")
    ]
    assert len(rows) == 1, f"docs/compatibility.md needs one matrix row for {name}"
    return rows[0]


@pytest.mark.parametrize("name", sorted(ALL_ADAPTERS))
def test_matrix_lists_each_adapter_with_its_contract_paths(name):
    contract = CONTRACTS["adapters"][name]
    row = _matrix_row(name)
    placeholder = CONTRACTS["skill"]
    assert f"`{contract['project'].replace(placeholder, '<name>')}`" in row
    if contract["global"] is not None:
        assert f"`{contract['global'].replace(placeholder, '<name>')}`" in row
    for var, cases in contract["env"].items():
        if cases["absolute"].startswith(f"${var}/"):
            assert f"`{var}`" in row


def test_matrix_scope_error_example_is_current():
    # docs/compatibility.md quotes the error for an unsupported scope
    messages = set()
    for adapter in ALL_ADAPTERS.values():
        if Scope.GLOBAL not in adapter.scopes:
            with pytest.raises(SkillError) as excinfo:
                adapter.check_scope(Scope.GLOBAL)
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
    assert f"sha256:{digest[:12]}" in CHANGELOG.read_text(encoding="utf-8"), (
        "record the adapter contract change in CHANGELOG.md under "
        f"[Unreleased], mentioning `sha256:{digest[:12]}`"
    )
