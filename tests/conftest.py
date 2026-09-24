"""Shared test setup and fixtures.

``evals/run_evals.py`` is a script, not part of the package; load it once as the
``run_evals`` module so the eval test files can ``import run_evals``.
"""

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

# the Windows error for a symlink created without SeCreateSymbolicLinkPrivilege
# (an unelevated account with Developer Mode off)
_ERROR_PRIVILEGE_NOT_HELD = 1314

#: environment variables that move an agent's user-level config directory
AGENT_HOME_VARS = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "COPILOT_HOME", "KIRO_HOME")


def _load_run_evals() -> None:
    script = Path(__file__).resolve().parent.parent / "evals" / "run_evals.py"
    spec = importlib.util.spec_from_file_location("run_evals", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclass field resolution looks the module up in sys.modules
    sys.modules["run_evals"] = module
    spec.loader.exec_module(module)


if "run_evals" not in sys.modules:
    _load_run_evals()


@pytest.fixture(autouse=True)
def _no_agent_home_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    # Global-scope paths follow these variables, so a developer's own agent
    # setup must not leak into the tests; tests that need one set it.
    for var in AGENT_HOME_VARS:
        monkeypatch.delenv(var, raising=False)


#: agent CLIs the eval runner's presets name; a real one costs money to run
_REAL_AGENT_CLIS = frozenset({"claude", "codex"})


@pytest.fixture(autouse=True)
def _no_real_agent_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    # The eval runner's presets run `claude`/`codex` from PATH, where a real,
    # logged-in CLI may be installed. Tests use stand-ins by absolute path;
    # a bare preset name reaching subprocess.run is a test bug, not a run.
    real_run = subprocess.run

    def guarded(cmd: object, *args: object, **kwargs: object) -> object:
        if isinstance(cmd, list) and cmd and cmd[0] in _REAL_AGENT_CLIS:
            raise AssertionError(f"a test tried to run the real agent CLI: {cmd}")
        return real_run(cmd, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", guarded)


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
