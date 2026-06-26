"""Adapter registry.

Maps an agent name to its adapter instance. ``cli`` and tests should import
``ADAPTERS`` rather than the concrete classes so adding a new agent is a one-line
change here.
"""

from __future__ import annotations

from .base import Adapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .kiro import KiroAdapter

ADAPTERS: dict[str, Adapter] = {
    adapter.name: adapter
    for adapter in (ClaudeAdapter(), CodexAdapter(), KiroAdapter())
}

__all__ = ["Adapter", "ADAPTERS"]
