"""Stage 2 — design the exam until it discriminates.

An audit where every candidate scores the same is worthless for hiring. The
strategist's real skill is not writing questions but writing *separating* ones — so
it authors an exam, screens the candidates, measures how well their scores separate
(``discrimination_index``), and if they don't, **hardens the exam and tries again**,
until the candidates are distinguishable or a round budget is spent. This is
AutoBencher-style separability optimization, run online per requirement.

``design_discriminating`` is generic: give it a ``generate(round, feedback) -> exam``
and a ``screen(exam) -> {candidate: score}`` and it drives the loop. The ``score`` can
be correctness (harder questions separate a weak model) or efficiency (cheapest/
fastest path separates equally-correct models) — Stage 2 and Stage 3 compose either
way. ``adaptive_text_audit`` wires it to the strategist + runner for text audits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .models import AuditSpec
from .pipeline import AuditPipeline
from .providers import Provider
from .runner import Runner
from .scoring import discrimination_index, is_discriminating


@dataclass
class RoundLog:
    index: int
    scores: dict[str, float]
    discrimination: float
    discriminating: bool


@dataclass
class AdaptiveResult:
    exam: Any                       # the chosen exam (most-discriminating round)
    rounds: list[RoundLog]
    discriminating: bool
    chosen_round: int

    def summary(self) -> str:
        lines = ["Adaptive audit design:"]
        for r in self.rounds:
            mark = "✅ separates" if r.discriminating else "✗ too close"
            sc = "  ".join(f"{k}:{v:.2f}" for k, v in r.scores.items())
            star = "  <- chosen" if r.index == self.chosen_round else ""
            lines.append(f"  round {r.index}: discrimination {r.discrimination:.2f} "
                         f"{mark}  [{sc}]{star}")
        return "\n".join(lines)


def _harden_feedback(scores: dict[str, float]) -> str:
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return (
        "Candidate scores were: "
        + ", ".join(f"{k}={v:.2f}" for k, v in ranked)
        + ". They are too close to separate. Raise difficulty so the gap widens."
    )


def design_discriminating(
    generate: Callable[[int, str | None], Any],
    screen: Callable[[Any], dict[str, float]],
    *,
    max_rounds: int = 3,
    min_discrimination: float = 0.15,
) -> AdaptiveResult:
    """Loop: generate exam -> screen candidates -> if not separating, harden & retry.

    Returns the most-discriminating exam seen (the first that clears the bar, or the
    best of ``max_rounds`` if none does)."""
    rounds: list[RoundLog] = []
    best_exam: Any = None
    best_d = -1.0
    best_round = 0
    feedback: str | None = None

    for i in range(max_rounds):
        exam = generate(i, feedback)
        scores = screen(exam)
        values = list(scores.values())
        d = discrimination_index(values)
        disc = is_discriminating(values, min_index=min_discrimination)
        rounds.append(RoundLog(i, scores, d, disc))
        if d > best_d:
            best_d, best_exam, best_round = d, exam, i
        if disc:
            return AdaptiveResult(exam, rounds, True, i)
        feedback = _harden_feedback(scores)

    return AdaptiveResult(best_exam, rounds, best_d >= min_discrimination, best_round)


def adaptive_text_audit(
    pipeline: AuditPipeline,
    requirement: str,
    candidates: list[Provider],
    *,
    competencies: list[str] | None = None,
    max_rounds: int = 3,
    min_discrimination: float = 0.15,
    score: str = "correctness",   # "correctness" (overall_score) or a custom key
) -> tuple[AuditSpec, AdaptiveResult]:
    """Adaptively author a text audit that separates ``candidates``.

    Screens with the runner each round and scores candidates by overall correctness
    (harder items separate a weaker candidate). Returns the chosen audit + the log.
    """
    runner = Runner(pipeline.grader)

    def generate(round_index: int, feedback: str | None) -> AuditSpec:
        return pipeline.strategist.design_audit(
            requirement, competencies=competencies, harden_feedback=feedback,
            version=round_index + 1,
        )

    def screen(audit: AuditSpec) -> dict[str, float]:
        return {c.name: runner.run(audit, c).overall_score for c in candidates}

    result = design_discriminating(
        generate, screen, max_rounds=max_rounds, min_discrimination=min_discrimination
    )
    return result.exam, result
