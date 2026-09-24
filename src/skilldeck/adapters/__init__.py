"""Adapter registry.

``ADAPTERS`` maps each supported agent's name to its native adapter; those
names are what a skill's ``supported-agents`` may list, and what ``--agent
all`` selects. ``LEGACY_ADAPTERS`` holds the opt-in older formats, selectable
only by name. ``cli`` and tests should import these rather than the concrete
classes, so adding a new agent is a one-line change here.
"""

from __future__ import annotations

from .base import Adapter, InstallState
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .copilot import CopilotAdapter
from .cursor import CursorAdapter
from .kiro import KiroAdapter
from .legacy import (
    CodexPromptAdapter,
    CopilotPromptAdapter,
    CursorRuleAdapter,
    KiroSteeringAdapter,
    LegacyAdapter,
)

ADAPTERS: dict[str, Adapter] = {
    adapter.name: adapter
    for adapter in (
        ClaudeAdapter(),
        CodexAdapter(),
        CopilotAdapter(),
        CursorAdapter(),
        KiroAdapter(),
    )
}

_COPILOT_PROMPT = CopilotPromptAdapter()
_CURSOR_RULE = CursorRuleAdapter()
_KIRO_STEERING = KiroSteeringAdapter()

LEGACY_ADAPTERS: dict[str, Adapter] = {
    adapter.name: adapter for adapter in (_COPILOT_PROMPT, _CURSOR_RULE, _KIRO_STEERING)
}

#: every adapter ``--agent`` can name
ALL_ADAPTERS: dict[str, Adapter] = {**ADAPTERS, **LEGACY_ADAPTERS}

#: for each agent, the older formats ``skilldeck migrate`` moves installs out
#: of, into that agent's native adapter
MIGRATIONS: dict[str, tuple[LegacyAdapter, ...]] = {
    "codex": (CodexPromptAdapter(),),
    "copilot": (_COPILOT_PROMPT,),
    "cursor": (_CURSOR_RULE,),
    "kiro": (_KIRO_STEERING,),
}

__all__ = [
    "ADAPTERS",
    "ALL_ADAPTERS",
    "LEGACY_ADAPTERS",
    "MIGRATIONS",
    "Adapter",
    "InstallState",
    "LegacyAdapter",
]
