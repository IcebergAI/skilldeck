import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "stamp_build_metadata.py"
_spec = importlib.util.spec_from_file_location("stamp_build_metadata", _SCRIPT)
assert _spec and _spec.loader
stamp_build_metadata = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp_build_metadata)


def _root(tmp_path: Path, version: str = "1.2.3") -> Path:
    (tmp_path / "src" / "skilldeck").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "skilldeck"\nversion = "{version}"\n'
    )
    (tmp_path / "src" / "skilldeck" / "_build_metadata.json").write_text("{}\n")
    return tmp_path


def test_stamp_build_metadata_requires_exact_tag_and_full_commit(tmp_path):
    root = _root(tmp_path)
    commit = "a" * 40
    stamp_build_metadata.stamp(root, "refs/tags/v1.2.3", commit)
    data = json.loads(stamp_build_metadata.metadata_path(root).read_text())
    assert data == {
        "schema_version": 1,
        "source_commit": commit,
        "source_ref": "refs/tags/v1.2.3",
        "source_repository": "https://github.com/IcebergAI/skilldeck",
    }
    stamp_build_metadata.stamp(root, "refs/tags/v1.2.3", commit, check=True)


@pytest.mark.parametrize(
    ("source_ref", "commit"),
    [
        ("refs/heads/main", "a" * 40),
        ("refs/tags/v1.2.4", "a" * 40),
        ("refs/tags/v1.2.3", "a" * 39),
        ("refs/tags/v1.2.3", "A" * 40),
        ("refs/tags/v1.2.3", "g" * 40),
    ],
)
def test_stamp_build_metadata_rejects_ambiguous_source(tmp_path, source_ref, commit):
    root = _root(tmp_path)
    with pytest.raises(ValueError):
        stamp_build_metadata.stamp(root, source_ref, commit)


def test_stamp_build_metadata_check_does_not_rewrite(tmp_path):
    root = _root(tmp_path)
    path = stamp_build_metadata.metadata_path(root)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        stamp_build_metadata.stamp(root, "refs/tags/v1.2.3", "b" * 40, check=True)
    assert path.read_bytes() == before
