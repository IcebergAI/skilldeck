"""Tests for the shared fixtures in ``conftest.py``."""

import pytest


def test_symlink_fixture_fails_on_errors_other_than_a_missing_privilege(
    tmp_path, symlink
):
    # Only "this platform/account cannot create symlinks" may skip a test. A
    # link path that already exists is a bug in the test and must fail it.
    taken = tmp_path / "taken"
    taken.write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        symlink(taken, tmp_path / "target")
