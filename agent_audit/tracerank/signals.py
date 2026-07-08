"""Turn a normalized Session into a SessionScore using implicit success signals.

The signal hierarchy (weight hard >> soft), per docs/FINDINGS_AND_OPEN_PROBLEMS.md:

* HARD (verifiable from the trace): tests passed / build ok / commit landed →
  strong +; tests failed / build error / revert → strong −. Near-ground-truth.
* MEDIUM (behavioral): rounds-to-satisfaction, tokens, explicit re-asks
  ("still broken", "again"), an interrupted/canceled final turn.
* SOFT (sentiment on the user's turns): "thanks/perfect/works" → +;
  "no/wrong/doesn't work/useless" → −. Useful but noisy — never decisive alone.

``outcome`` ∈ [0,1] is the estimated task success; ``confidence`` says how much
*hard* evidence backed it (so the leaderboard can down-weight guesses). Everything
is deterministic and inspectable — an LLM labeler can later override ``outcome`` on
low-confidence sessions, anchored to the transcript (see the module docstring in
``__init__``). ``failure_tags`` feed the skill-hint generator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Role, Session

# --- lexicons (lowercased, word-ish matched) ---------------------------------
_POS = ["thanks", "thank you", "perfect", "great", "awesome", "works",
        "working now", "that works", "lgtm", "ship it", "exactly", "nice",
        "correct", "solved", "fixed it", "looks good"]
_NEG = ["doesn't work", "does not work", "not working", "still broken",
        "still failing", "still not", "that's wrong", "thats wrong", "incorrect",
        "no that", "nonsense", "useless", "wrong again", "not what i", "stop",
        "terrible", "garbage", "you broke", "makes no sense", "hallucinat"]
_REASK = ["again", "still", "retry", "same error", "same problem", "as i said",
          "i already", "no,", "no.", "not that"]
_ANGER = ["wtf", "ffs", "for f", "damn it", "seriously", "?!", "ugh", "come on"]

# HARD outcome markers, matched against TOOL turns and agent/tool text.
_PASS = [r"\btests? passed\b", r"\ball tests? pass", r"\b0 failing\b",
         r"\bbuild (succeeded|successful|ok)\b", r"\bcompiled successfully\b",
         r"\bexit code 0\b", r"\b✓\b", r"\bpassing\b"]
_FAIL = [r"\btests? failed\b", r"\b\d+ failing\b", r"\bbuild failed\b",
         r"\bcompilation error\b", r"\btraceback\b", r"\bexit code [1-9]\b",
         r"\berror:", r"\bexception\b", r"\breverted\b"]


def _has(text: str, needles: list[str]) -> bool:
    t = text.lower()
    return any(n in t for n in needles)


def _rx(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


@dataclass
class SessionScore:
    session_id: str
    agent: str
    task_kind: str = ""
    outcome: float = 0.5          # estimated success in [0,1]
    confidence: float = 0.0       # how much HARD evidence backed the outcome, [0,1]
    rounds: int = 0
    tokens: int = 0
    signals: dict[str, float] = field(default_factory=dict)
    failure_tags: list[str] = field(default_factory=list)


def score_session(s: Session) -> SessionScore:
    """Estimate task success from implicit signals. Deterministic and inspectable."""
    signals: dict[str, float] = {}
    tags: list[str] = []
    hard_evidence = 0

    # ---- HARD: verifiable outcome markers in tool/agent turns ----
    tool_text = " \n".join(t.text for t in s.turns if t.role in (Role.TOOL, Role.AGENT))
    tool_fail = any(t.role is Role.TOOL and t.tool_ok is False for t in s.turns)
    tool_pass = any(t.role is Role.TOOL and t.tool_ok is True for t in s.turns)
    if _rx(tool_text, _PASS) or tool_pass:
        signals["hard_pass"] = 1.0
        hard_evidence += 1
    if _rx(tool_text, _FAIL) or tool_fail:
        signals["hard_fail"] = 1.0
        hard_evidence += 1
        tags.append("verifiable_failure_in_trace")

    # ---- explicit user feedback (votes) — strongest non-derived signal ----
    votes = [t.vote for t in s.turns if t.vote is not None]
    if votes:
        signals["vote"] = sum(votes) / len(votes)
        hard_evidence += 1

    # ---- MEDIUM: structure & behavior ----
    if s.ended_naturally is False:
        signals["force_stopped"] = 1.0
        tags.append("session_force_stopped")
    if s.turns and s.turns[-1].canceled:
        signals["last_turn_canceled"] = 1.0
        tags.append("final_response_canceled")

    user_text = " \n".join(t.text for t in s.user_turns)
    if _has(user_text, _REASK):
        signals["reask"] = 1.0
        tags.append("user_had_to_repeat_or_correct")

    # ---- SOFT: sentiment across the user's turns (later turns weigh more) ----
    pos = neg = 0.0
    n = len(s.user_turns)
    for i, t in enumerate(s.user_turns):
        w = 1.0 + i / max(1, n)           # recency weight
        if _has(t.text, _POS):
            pos += w
        if _has(t.text, _NEG):
            neg += w
        if _has(t.text, _ANGER):
            neg += 1.5 * w
            if "user_frustration" not in tags:
                tags.append("user_frustration")
    if pos:
        signals["sentiment_pos"] = pos
    if neg:
        signals["sentiment_neg"] = neg

    # ---- combine into an outcome estimate ----
    # Start neutral; hard signals move it a lot, soft signals a little.
    score = 0.5
    score += 0.40 * signals.get("hard_pass", 0.0)
    score -= 0.40 * signals.get("hard_fail", 0.0)
    score += 0.30 * max(0.0, signals.get("vote", 0.0))
    score += 0.30 * min(0.0, signals.get("vote", 0.0))
    score += 0.12 * min(1.0, signals.get("sentiment_pos", 0.0) / 2.0)
    score -= 0.18 * min(1.0, signals.get("sentiment_neg", 0.0) / 2.0)
    score -= 0.15 * signals.get("force_stopped", 0.0)
    score -= 0.10 * signals.get("last_turn_canceled", 0.0)
    score -= 0.08 * signals.get("reask", 0.0)
    # A clean natural end with no negatives is mildly positive.
    if s.ended_naturally and not any(k in signals for k in
                                     ("hard_fail", "sentiment_neg", "reask",
                                      "force_stopped", "last_turn_canceled")):
        score += 0.10
    outcome = max(0.0, min(1.0, score))

    # confidence: hard evidence dominates; sentiment-only sessions are low-confidence
    confidence = min(1.0, 0.5 * hard_evidence + 0.15 * (1 if (pos or neg) else 0))

    if outcome < 0.5 and not tags:
        tags.append("weak_outcome_no_clear_cause")

    return SessionScore(
        session_id=s.session_id, agent=s.agent, task_kind=s.task_kind,
        outcome=round(outcome, 3), confidence=round(confidence, 3),
        rounds=s.rounds, tokens=s.total_tokens, signals=signals, failure_tags=tags,
    )
