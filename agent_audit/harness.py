"""Evaluation harness: does audit-driven hiring beat naive selection?

The falsifiable claim under test (README / docs/RESEARCH.md): *an LLM-authored,
requirement-specific audit predicts on-the-job performance better than picking by
leaderboard rank or by "just use the biggest model."*

Protocol, per requirement case:

1. The strategist authors an audit from the requirement (never from the job tasks).
2. All candidates are screened; a team is hired (``AuditPipeline``).
3. Every strategy then answers the **held-out job tasks** — real work the audit
   never saw:
     * ``audit_hire``   — each job task is routed to the team member staffed on
       that task's competency (lead as fallback). This is the treatment.
     * baselines        — a single fixed provider answers everything
       (biggest model, leaderboard pick, cheapest model, ...).
4. Job answers are graded by the same judge/grader, and cost is accounted from
   provider token usage — so the result is a quality *and* cost comparison.

Everything is provider-agnostic: run it offline with mocks (tests) or with real
Claude models (``experiments/run_harness.py``).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .grader import Grader
from .models import Check, TestCase
from .pipeline import AuditPipeline, AuditRun
from .providers import Provider


@dataclass
class JobTask:
    """A held-out, on-the-job task — NOT part of the audit."""

    id: str
    competency: str          # which team role this work belongs to
    prompt: str
    checks: list[Check]      # ground-truth-ish grading of the real work
    weight: float = 1.0

    def as_test_case(self) -> TestCase:
        return TestCase(id=self.id, competency=self.competency, prompt=self.prompt,
                        checks=self.checks, weight=self.weight)


@dataclass
class RequirementCase:
    name: str
    requirement: str
    job_tasks: list[JobTask]

    @property
    def competencies(self) -> list[str]:
        return list(dict.fromkeys(t.competency for t in self.job_tasks))


@dataclass
class StrategyResult:
    strategy: str
    executor: str            # provider/team description that did the job
    job_score: float         # weighted mean over job tasks, 0..1
    cost_usd: float          # marginal cost of doing the job (audit cost excluded)
    per_task: dict[str, float] = field(default_factory=dict)


@dataclass
class CaseReport:
    case: str
    requirement: str
    audit_cost_usd: float    # one-time cost of authoring + running the audit
    audit_run_summary: str
    strategies: list[StrategyResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HarnessReport:
    cases: list[CaseReport]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        lines: list[str] = []
        totals: dict[str, list[float]] = {}
        for case in self.cases:
            lines.append(f"\n=== {case.case} ===")
            lines.append(f"(audit overhead: ${case.audit_cost_usd:.4f})")
            for s in sorted(case.strategies, key=lambda s: s.job_score, reverse=True):
                lines.append(
                    f"  {s.strategy:<18} job score {s.job_score:.2f}   "
                    f"cost ${s.cost_usd:.4f}   [{s.executor}]"
                )
                totals.setdefault(s.strategy, []).append(s.job_score)
        lines.append("\n=== Mean job score across cases ===")
        for strategy, scores in sorted(totals.items(), key=lambda kv: -sum(kv[1])):
            lines.append(f"  {strategy:<18} {sum(scores) / len(scores):.2f}")
        return "\n".join(lines)


def _cost(providers: list[Provider]) -> float:
    total = 0.0
    for p in providers:
        fn = getattr(p, "cost_usd", None)
        if callable(fn):
            total += fn()
    return total


class Harness:
    def __init__(
        self,
        pipeline: AuditPipeline,
        grader: Grader,
        candidates: list[Provider],
        baselines: dict[str, Provider],
    ) -> None:
        """``baselines`` maps strategy name -> the single provider it always uses,
        e.g. {"biggest_model": opus46, "leaderboard_pick": sonnet5, "cheapest": haiku45}.
        Baseline providers may be the same objects as candidates."""
        self.pipeline = pipeline
        self.grader = grader
        self.candidates = candidates
        self.baselines = baselines

    def run_case(self, case: RequirementCase) -> CaseReport:
        all_providers = list({id(p): p for p in
                              [*self.candidates, *self.baselines.values()]}.values())

        # Phase 1: audit + hire (the one-time overhead the treatment pays). The
        # strategist is pinned to the case's competency vocabulary so the hired
        # team's roles line up with how the held-out job tasks are tagged.
        before_audit = _cost(all_providers)
        audit_run = self.pipeline.run(
            case.requirement, self.candidates, competencies=case.competencies
        )
        audit_cost = _cost(all_providers) - before_audit

        strategies: list[StrategyResult] = []

        # Treatment: audit-hired team, routed per competency.
        strategies.append(self._run_team(case, audit_run, all_providers))

        # Baselines: one fixed provider answers every job task.
        for name, provider in self.baselines.items():
            strategies.append(self._run_single(case, name, provider, all_providers))

        return CaseReport(
            case=case.name,
            requirement=case.requirement,
            audit_cost_usd=audit_cost,
            audit_run_summary=audit_run.summary(),
            strategies=strategies,
        )

    def run(self, cases: list[RequirementCase]) -> HarnessReport:
        return HarnessReport(cases=[self.run_case(c) for c in cases])

    # --- strategy executors ---------------------------------------------------

    def _route(self, audit_run: AuditRun, competency: str) -> Provider | None:
        by_name = {p.name: p for p in self.candidates}
        for a in audit_run.team.assignments:
            if a.competency == competency and a.candidate:
                return by_name.get(a.candidate)
        if audit_run.team.lead:
            return by_name.get(audit_run.team.lead)
        return None

    def _run_team(self, case: RequirementCase, audit_run: AuditRun,
                  all_providers: list[Provider]) -> StrategyResult:
        before = _cost(all_providers)
        per_task: dict[str, float] = {}
        routing: dict[str, str] = {}
        for task in case.job_tasks:
            provider = self._route(audit_run, task.competency)
            if provider is None:  # nobody hired at all — the strategy scores zero
                per_task[task.id] = 0.0
                routing[task.competency] = "(unstaffed)"
                continue
            routing[task.competency] = provider.name
            per_task[task.id] = self._do_task(task, provider)
        return StrategyResult(
            strategy="audit_hire",
            executor="; ".join(f"{c}->{n}" for c, n in routing.items()),
            job_score=_weighted(case.job_tasks, per_task),
            cost_usd=_cost(all_providers) - before,
            per_task=per_task,
        )

    def _run_single(self, case: RequirementCase, name: str, provider: Provider,
                    all_providers: list[Provider]) -> StrategyResult:
        before = _cost(all_providers)
        per_task = {task.id: self._do_task(task, provider) for task in case.job_tasks}
        return StrategyResult(
            strategy=name,
            executor=provider.name,
            job_score=_weighted(case.job_tasks, per_task),
            cost_usd=_cost(all_providers) - before,
            per_task=per_task,
        )

    def _do_task(self, task: JobTask, provider: Provider) -> float:
        error = ""
        try:
            response = provider.complete(task.prompt)
        except Exception as exc:
            response, error = "", f"{type(exc).__name__}: {exc}"
        result = self.grader.grade_case(task.as_test_case(), response, error=error)
        return result.score


def _weighted(tasks: list[JobTask], per_task: dict[str, float]) -> float:
    total_w = sum(t.weight for t in tasks)
    if not total_w:
        return 0.0
    return sum(per_task.get(t.id, 0.0) * t.weight for t in tasks) / total_w
