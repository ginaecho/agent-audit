"""Trace-based agent ranking — capability from *real usage*, not synthetic tests.

Auto-generated benchmarks hit a ceiling (see docs/FINDINGS_AND_OPEN_PROBLEMS.md):
a model can't author items harder than its own blind spots, most tests tie, and
anything it authors is trivially overfit. So instead of *authoring* tests, this
module *harvests ground truth that already exists* — the outcomes of real agent
sessions (VS Code / GitHub Copilot chats, Claude Code sessions, …).

Pipeline:
  adapter (source-specific)  ->  normalized Session[]   (model.py)
  Session                    ->  SessionScore            (signals.py)
  SessionScore[]             ->  Leaderboard             (leaderboard.py)
  failures across sessions   ->  per-agent skill hints   (hints.py)

The scoring philosophy is shared with the rest of the package: an outcome signal
(did the task succeed?) weighted by efficiency (rounds / tokens to satisfaction),
and — critically — *difficulty-adjusted* so an agent handed harder work isn't
penalized for it.
"""

from .model import Session, Turn, Role
from .signals import SessionScore, score_session
from .leaderboard import AgentRanking, Leaderboard, build_leaderboard
from .hints import SkillHint, hints_for_agent

__all__ = [
    "Session", "Turn", "Role",
    "SessionScore", "score_session",
    "AgentRanking", "Leaderboard", "build_leaderboard",
    "SkillHint", "hints_for_agent",
]
