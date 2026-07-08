"""Turn an agent's recurring failure tags into concrete improvement *skills*.

This is the payoff of trace ranking and the same loop as ``coach.py``, but fed by
*real* failures instead of synthetic audit misses: cluster the failure tags across
an agent's sessions, and for each frequent one emit an actionable skill the agent
can adopt (attachable via ``SkilledProvider``). Deterministic and offline; a strong
model can rewrite these into richer skill text, but the *diagnosis* comes from data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .signals import SessionScore

# tag -> (short diagnosis, skill text to attach)
_PLAYBOOK: dict[str, tuple[str, str]] = {
    "verifiable_failure_in_trace": (
        "Ships changes that fail their own tests/build.",
        "Before declaring a task done, run the project's tests/build and read the "
        "output. If anything fails, fix it and re-run — never hand back red."),
    "user_had_to_repeat_or_correct": (
        "User frequently has to repeat or re-state the request.",
        "Restate the goal in your own words and confirm scope before large changes. "
        "If a reply gets corrected, diff your understanding against the correction "
        "before trying again."),
    "session_force_stopped": (
        "Sessions get force-stopped mid-task (a sign of bad/derailed output).",
        "Work in small, verifiable increments and check in early. If unsure of the "
        "direction, ask one focused question rather than producing a long wrong answer."),
    "final_response_canceled": (
        "The final response is often canceled by the user.",
        "Front-load the answer: give the result first, then detail. Avoid long "
        "preambles the user will interrupt."),
    "user_frustration": (
        "User shows frustration (anger/complaints) during sessions.",
        "When the user pushes back, stop and acknowledge the specific problem, then "
        "address exactly that — don't repeat the same approach with more words."),
    "weak_outcome_no_clear_cause": (
        "Sessions end weakly with no clear success signal.",
        "End tasks with an explicit verification step and a one-line summary of what "
        "was accomplished, so success is legible instead of ambiguous."),
}


@dataclass
class SkillHint:
    tag: str
    count: int
    diagnosis: str
    skill_text: str


def hints_for_agent(scores: list[SessionScore], agent: str,
                    *, min_count: int = 2) -> list[SkillHint]:
    """Rank an agent's recurring failures and emit a skill for each frequent one."""
    tags = Counter(t for s in scores if s.agent == agent for t in s.failure_tags)
    hints: list[SkillHint] = []
    for tag, count in tags.most_common():
        if count < min_count or tag not in _PLAYBOOK:
            continue
        diag, skill = _PLAYBOOK[tag]
        hints.append(SkillHint(tag=tag, count=count, diagnosis=diag, skill_text=skill))
    return hints
