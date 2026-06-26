from pathlib import Path

import pytest

from skilldeck.adapters import ADAPTERS
from skilldeck.registry import Skill
from skilldeck.targets import Scope


@pytest.fixture
def skill():
    return Skill(
        name="demo",
        description="a demo skill",
        category="testing",
        version="0.1.0",
        supported_agents=("claude", "codex"),
        body="DEMO BODY",
        path=Path("/nowhere"),
    )


def test_claude_renders_frontmatter(skill):
    out = ADAPTERS["claude"].render(skill)
    assert out.startswith("---\n")
    assert "name: demo" in out
    assert out.rstrip().endswith("DEMO BODY")


def test_codex_and_kiro_render_body_as_is(skill):
    assert ADAPTERS["codex"].render(skill) == "DEMO BODY"
    assert ADAPTERS["kiro"].render(skill) == "DEMO BODY"


def test_global_scope_resolves_against_home(skill, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    dest = ADAPTERS["claude"].destination(skill, Scope.GLOBAL)
    assert dest == tmp_path / ".claude/skills/demo/SKILL.md"


def test_paths_are_agent_specific(skill):
    assert ADAPTERS["claude"].relative_path(skill) == Path(".claude/skills/demo/SKILL.md")
    assert ADAPTERS["codex"].relative_path(skill) == Path(".codex/prompts/demo.md")
    assert ADAPTERS["kiro"].relative_path(skill) == Path(".kiro/steering/demo.md")


def test_supports_respects_supported_agents(skill):
    assert ADAPTERS["claude"].supports(skill)
    assert not ADAPTERS["kiro"].supports(skill)


def test_install_and_uninstall_roundtrip(skill, tmp_path):
    adapter = ADAPTERS["claude"]
    dest = adapter.install(skill, Scope.PROJECT, project_root=tmp_path)
    assert dest.is_file()
    assert dest == tmp_path / ".claude/skills/demo/SKILL.md"

    removed = adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path)
    assert removed == dest
    assert not dest.exists()
    # the per-skill directory is cleaned up, not left empty
    assert not dest.parent.exists()
    # second uninstall is a no-op
    assert adapter.uninstall(skill, Scope.PROJECT, project_root=tmp_path) is None
