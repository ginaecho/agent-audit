"""Normalized trace model — the source-agnostic shape every adapter produces.

Every trace source (VS Code Copilot, Claude Code, …) is messy and different; each
adapter's only job is to flatten its native format into these dataclasses so the
signal/leaderboard/hint code never has to know where a trace came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    USER = "user"
    AGENT = "agent"      # the assistant / model / agent response
    TOOL = "tool"        # a tool call or its result (edits, terminal, test runs)


@dataclass
class Turn:
    """One message in a session, already normalized."""

    role: Role
    text: str = ""
    ts: float | None = None                 # epoch seconds if known
    tokens: int = 0                          # best-effort token count for this turn
    # Optional structured facts an adapter may recover (all best-effort):
    tool_name: str | None = None             # e.g. "editFile", "runInTerminal"
    tool_ok: bool | None = None              # did the tool call succeed?
    canceled: bool = False                   # user interrupted / stopped this turn
    vote: int | None = None                  # explicit feedback: +1 up, -1 down
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """One end-to-end conversation with a single agent, normalized.

    ``agent`` is what we rank (a model id, a Copilot mode, an agent name). ``task_kind``
    lets the leaderboard compare like-with-like (difficulty adjustment) — an adapter
    should fill it if it can infer one (language, "debug", "refactor", …), else "".
    """

    session_id: str
    agent: str
    turns: list[Turn] = field(default_factory=list)
    task_kind: str = ""
    source: str = ""                         # "copilot-vscode", "claude-code", …
    ended_naturally: bool | None = None      # False if the adapter knows it was force-stopped
    meta: dict[str, Any] = field(default_factory=dict)

    # --- convenience views -------------------------------------------------
    @property
    def user_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role is Role.USER]

    @property
    def agent_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role is Role.AGENT]

    @property
    def rounds(self) -> int:
        """User<->agent exchanges — a proxy for how much back-and-forth it took."""
        return len(self.user_turns)

    @property
    def total_tokens(self) -> int:
        return sum(t.tokens for t in self.turns)

    def last_user_text(self) -> str:
        us = self.user_turns
        return us[-1].text if us else ""
