"""Tests for scripts/_pyproject.py, the shared ``[project].version`` reader."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "_pyproject.py"
_spec = importlib.util.spec_from_file_location("_pyproject", _SCRIPT)
assert _spec and _spec.loader
pyproject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pyproject)

# A decoy ``version`` key before and after the real one, in other tables.
DECOYS = """\
[tool.decoy]
version = "9.9.9"

[project]
name = "demo"
version = "1.2.3"  # the real one
dependencies = [
    "click>=8.1",
]

[project.urls]
Homepage = "https://example.invalid"

[[tool.more]]
version = "8.8.8"
"""


def test_reads_the_repo_version_consistently():
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = pyproject.project_version(_ROOT)
    # the fallback scan (Python 3.10) and the TOML parser (3.11+) must agree
    assert version == pyproject.scan_project_version(text)
    assert version == pyproject.parse_project_version(text)


@pytest.mark.parametrize(
    "reader", ["scan_project_version", "parse_project_version"], ids=str
)
def test_only_the_project_table_counts(reader):
    assert getattr(pyproject, reader)(DECOYS) == "1.2.3"


def test_version_span_points_at_the_project_value():
    start, end = pyproject.version_span(DECOYS)
    assert DECOYS[start:end] == "1.2.3"
    assert DECOYS[:start].endswith('[project]\nname = "demo"\nversion = "')


@pytest.mark.parametrize(
    "text, message",
    [
        ('[tool.x]\nversion = "1.0.0"\n', "no \\[project\\] table"),
        ('[project]\nname = "x"\n\n[tool.x]\nversion = "1.0.0"\n', "no \\[project\\]"),
        ('[project.urls]\nversion = "1.0.0"\n', "no \\[project\\]"),
    ],
)
@pytest.mark.parametrize("reader", ["scan_project_version", "parse_project_version"])
def test_missing_project_version_is_an_error(reader, text, message):
    with pytest.raises(pyproject.PyprojectError, match=message):
        getattr(pyproject, reader)(text)


@pytest.mark.parametrize(
    "text, message",
    [
        ('[project]\nversion = "1.0.0"\n[project]\n', "more than one"),
        ('[project]\nversion = "1.0.0"\nversion = "2.0.0"\n', "more than once"),
        ('[project]\nversion = ""\n', "empty"),
        ("[project]\nversion = '1.0.0'\n", "no \\[project\\] version"),
    ],
)
def test_scan_fails_loudly_on_forms_it_does_not_understand(text, message):
    with pytest.raises(pyproject.PyprojectError, match=message):
        pyproject.scan_project_version(text)


def test_cli_prints_the_version():
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert result.stdout.strip() == pyproject.project_version(_ROOT)


def test_unreadable_pyproject_is_a_clean_error(tmp_path):
    with pytest.raises(pyproject.PyprojectError, match="cannot read"):
        pyproject.project_version(tmp_path)
