"""Shared test setup.

``evals/run_evals.py`` is a script, not part of the package; load it once as the
``run_evals`` module so the eval test files can ``import run_evals``.
"""

import importlib.util
import sys
from pathlib import Path


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
