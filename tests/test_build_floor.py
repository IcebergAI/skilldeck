"""CI builds with the oldest hatchling that ``[build-system]`` allows (#110)."""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _release(version: str) -> tuple[int, ...]:
    parts = [int(part) for part in version.split(".")]
    while len(parts) > 1 and parts[-1] == 0:  # 1.27 == 1.27.0
        parts.pop()
    return tuple(parts)


def test_ci_builds_with_the_declared_hatchling_floor():
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    floor = re.search(r'"hatchling>=([0-9.]+)[,"]', pyproject)
    pinned = re.findall(r"hatchling==([0-9.]+)", ci)
    assert floor, "[build-system] requires must give hatchling a >= floor"
    assert pinned, "ci.yml no longer builds with the hatchling floor"
    assert {_release(v) for v in pinned} == {_release(floor.group(1))}, (
        f"ci.yml builds with hatchling {pinned}, but pyproject.toml's floor is "
        f"{floor.group(1)}; keep them in step"
    )
