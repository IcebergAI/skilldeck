import pytest

#: environment variables that move an agent's user-level config directory
AGENT_HOME_VARS = ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "COPILOT_HOME", "KIRO_HOME")


@pytest.fixture(autouse=True)
def _no_agent_home_overrides(monkeypatch):
    # Global-scope paths follow these variables, so a developer's own agent
    # setup must not leak into the tests; tests that need one set it.
    for var in AGENT_HOME_VARS:
        monkeypatch.delenv(var, raising=False)
