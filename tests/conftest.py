"""Shared pytest fixtures."""

from collections.abc import Callable
from pathlib import Path

import pytest

# the Windows error for a symlink created without SeCreateSymbolicLinkPrivilege
# (an unelevated account with Developer Mode off)
_ERROR_PRIVILEGE_NOT_HELD = 1314


@pytest.fixture
def symlink() -> Callable[[Path, Path], None]:
    """Return ``make(link, target)``, which skips the test if symlinks are denied.

    Windows lets only elevated users (or Developer Mode) create symlinks, so a
    test that needs one skips there with the reason instead of failing. Every
    other error (``link`` already exists, a missing parent directory, ...) is
    a bug in the test and still fails it: these are security regression tests,
    and a skip is easy to miss.
    """

    def make(link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except NotImplementedError as exc:
            pytest.skip(f"symlinks are not supported on this platform: {exc}")
        except OSError as exc:
            if getattr(exc, "winerror", None) != _ERROR_PRIVILEGE_NOT_HELD:
                raise
            pytest.skip(f"this account may not create symlinks: {exc}")

    return make
