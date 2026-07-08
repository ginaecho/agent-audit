"""Efficiency-weighted scoring and discrimination metrics.

Correctness alone often fails to separate capable models: on an easy task every
candidate is "right" and the audit yields zero hiring signal (see docs/RESULTS.md,
run 1). Two complementary fixes, both the strategist's responsibility:

1. **Discriminate by design** — an exam where everyone scores the same is useless.
   ``discrimination_index`` measures how well a set of scores separates candidates,
   so the strategist can keep hardening (or re-targeting) items until it does.

2. **Reward the shortest / cheapest path to a correct answer.** A correct answer in
   fewer tokens / tool-calls / steps / dollars beats a correct answer that cost more.
   This turns "everyone passed" into a strict ordering and rewards exactly the trait
   you hire for — capability per unit cost. The same task that ties on correctness
   discriminates sharply on efficiency.

``Effort`` is provider-agnostic: text-only candidates report ``tokens`` (and/or
``usd``); agentic candidates that write & run code or call MCP tools also report
``tool_calls`` / ``steps`` — so "shortest path" is literal, not a metaphor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import pstdev


@dataclass
class Effort:
    """What it cost a candidate to (attempt to) solve one task."""

    tokens: int = 0
    tool_calls: int = 0
    steps: int = 0          # agent-loop turns to reach a result
    latency_s: float = 0.0
    usd: float = 0.0

    def cost(self, weights: dict[str, float] | None = None) -> float:
        """A single comparable scalar. Defaults to dollars if priced, else tokens;
        pass ``weights`` to fold in path length (e.g. {"tokens":1, "tool_calls":500,
        "steps":2000}) for agentic tasks where fewer steps should count."""
        if weights:
            return (
                weights.get("tokens", 0.0) * self.tokens
                + weights.get("tool_calls", 0.0) * self.tool_calls
                + weights.get("steps", 0.0) * self.steps
                + weights.get("latency_s", 0.0) * self.latency_s
                + weights.get("usd", 0.0) * self.usd
            )
        if self.usd > 0:
            return self.usd
        return float(self.tokens or self.tool_calls or self.steps or self.latency_s)


@dataclass
class Attempt:
    """One candidate's result on one task: how right, and how expensive."""

    candidate: str
    correctness: float          # 0..1 from the grader
    effort: Effort = field(default_factory=Effort)


def efficiency_score(
    correctness: float,
    cost: float,
    cost_min: float,
    *,
    correctness_bar: float = 1.0,
) -> float:
    """Correctness-gated efficiency in 0..1.

    A candidate below ``correctness_bar`` scores 0 (being cheap is worthless if you
    are wrong). Among candidates that clear the bar, the cheapest gets 1.0 and the
    rest are scaled down by how much more they spent: ``correctness * cost_min/cost``.
    """
    if correctness < correctness_bar:
        return 0.0
    if cost <= 0 or cost_min <= 0:
        return correctness
    return correctness * (cost_min / cost)


def rank_task(
    attempts: list[Attempt],
    *,
    correctness_bar: float = 1.0,
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Efficiency score per candidate on ONE task (cheapest correct answer wins)."""
    correct = [a for a in attempts if a.correctness >= correctness_bar]
    cost_min = min((a.effort.cost(weights) for a in correct), default=0.0)
    return {
        a.candidate: efficiency_score(a.correctness, a.effort.cost(weights), cost_min,
                                      correctness_bar=correctness_bar)
        for a in attempts
    }


def efficiency_leaderboard(
    task_attempts: list[list[Attempt]],
    *,
    correctness_bar: float = 1.0,
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Mean efficiency score per candidate across many tasks."""
    totals: dict[str, list[float]] = {}
    for attempts in task_attempts:
        for cand, score in rank_task(attempts, correctness_bar=correctness_bar,
                                     weights=weights).items():
            totals.setdefault(cand, []).append(score)
    return {c: sum(v) / len(v) for c, v in totals.items()}


def discrimination_index(scores: list[float]) -> float:
    """How well a score set separates candidates, 0..1.

    0.0 => useless (everyone scored the same — no hiring signal). Higher => the exam
    (or scoring) actually distinguishes candidates. Defined as the spread (max-min);
    ``discrimination_stdev`` gives the dispersion variant.
    """
    if len(scores) < 2:
        return 0.0
    return max(scores) - min(scores)


def discrimination_stdev(scores: list[float]) -> float:
    return pstdev(scores) if len(scores) >= 2 else 0.0


def is_discriminating(scores: list[float], *, min_index: float = 0.15) -> bool:
    """Whether an exam separated candidates enough to be worth hiring on.

    The strategist should keep hardening the exam while this is False.
    """
    return discrimination_index(scores) >= min_index
