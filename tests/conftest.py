"""Shared pytest fixtures."""

from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def symlink() -> Callable[[Path, Path], None]:
    """Return ``make(link, target)``, which skips the test if symlinks are denied.

    Windows lets only elevated users (or Developer Mode) create symlinks, so a
    test that needs one skips there with the reason instead of failing.
    """

    def make(link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"cannot create symlinks on this platform/account: {exc}")

    return make
