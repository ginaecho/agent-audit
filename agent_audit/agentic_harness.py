"""Agentic harness: does audit-hiring beat naive picks on EXECUTABLE held-out tasks?

Same question as ``harness.py``, but the candidates are coding agents and both the
screening audit and the held-out job are executable coding tasks scored by
correctness AND efficiency (shortest path to green — steps / tokens / speed):

1. screen every candidate on the screening tasks (the audit); compute a per-competency
   efficiency score (correctness-gated, cheapest/fastest correct wins) and hire the
   best candidate per competency;
2. run the held-out job tasks under each strategy:
     * ``audit_hire`` — each job task routed to the candidate hired for its competency;
     * baselines — one fixed candidate does everything (always-opus, always-haiku, ...);
3. report quality (raw pass-rate) AND efficiency (capability per unit cost) per strategy.

Provider-agnostic: run offline with mock coding agents (tests), with real models via
``AnthropicProvider``, or with session models replayed through ``MockProvider`` (the
free subagent-validation path — see experiments/).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .execution import CodingTask, Runner, run_code, run_coding_audit
from .providers import Provider
from .scoring import AGENTIC_WEIGHTS, Attempt, rank_task


@dataclass
class AgenticCase:
    name: str
    requirement: str
    screening: list[CodingTask]   # the audit — used to hire
    job: list[CodingTask]          # held-out — what strategies are measured on

    @property
    def competencies(self) -> list[str]:
        return list(dict.fromkeys(t.competency for t in [*self.screening, *self.job]))


@dataclass
class StrategyResult:
    strategy: str
    executor: str
    quality: float          # raw mean pass-rate over job tasks (0..1)
    efficiency: float        # capability-per-cost over job tasks (0..1)
    per_task_quality: dict[str, float] = field(default_factory=dict)


@dataclass
class AgenticCaseReport:
    case: str
    hires: dict[str, str]           # competency -> hired candidate
    strategies: list[StrategyResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        lines = [f"=== {self.case} ===",
                 "hires: " + ", ".join(f"{k}->{v}" for k, v in self.hires.items()), ""]
        lines.append(f"  {'strategy':<22} {'quality':>8} {'efficiency':>11}")
        for s in sorted(self.strategies, key=lambda s: (-s.quality, -s.efficiency)):
            lines.append(f"  {s.strategy:<22} {s.quality:>8.2f} {s.efficiency:>11.2f}   "
                         f"[{s.executor}]")
        return "\n".join(lines)


def _transpose(by_cand: dict[str, list[Attempt]]) -> list[list[Attempt]]:
    names = list(by_cand)
    n = len(next(iter(by_cand.values()))) if by_cand else 0
    return [[by_cand[name][i] for name in names] for i in range(n)]


class AgenticHarness:
    def __init__(
        self,
        candidates: list[Provider],
        baselines: dict[str, str],
        *,
        runner: Runner = run_code,
        weights: dict[str, float] | None = None,
        max_steps: int = 3,
    ) -> None:
        """``baselines`` maps a strategy name -> a candidate *name* in the pool, e.g.
        {"always_opus": "opus", "always_haiku": "haiku"}. Keeping baselines inside the
        candidate pool means every strategy is scored against the same field, per task."""
        self.candidates = candidates
        self.baselines = baselines
        self.runner = runner
        self.weights = weights or AGENTIC_WEIGHTS
        self.max_steps = max_steps

    def run_case(self, case: AgenticCase) -> AgenticCaseReport:
        # 1. Screen every candidate on the audit; hire best-per-competency by efficiency.
        screened = run_coding_audit(self.candidates, case.screening,
                                    max_steps=self.max_steps, runner=self.runner)
        comp_scores: dict[str, dict[str, list[float]]] = {}
        for i, task in enumerate(case.screening):
            ranked = rank_task([screened[c.name][i] for c in self.candidates],
                               weights=self.weights)
            for cand, sc in ranked.items():
                comp_scores.setdefault(task.competency, {}).setdefault(cand, []).append(sc)
        hires = {
            comp: max({c: sum(v) / len(v) for c, v in per.items()}.items(),
                      key=lambda kv: kv[1])[0]
            for comp, per in comp_scores.items()
        }

        # 2. Every candidate solves the held-out job once; score any routing from it.
        job = run_coding_audit(self.candidates, case.job,
                               max_steps=self.max_steps, runner=self.runner)
        task_rank = [rank_task([job[c.name][i] for c in self.candidates], weights=self.weights)
                     for i in range(len(case.job))]
        default = self.candidates[0].name

        def result(strategy: str, pick) -> StrategyResult:
            per_q, effs, desc = {}, [], {}
            for i, task in enumerate(case.job):
                cand = pick(task)
                desc[task.competency] = cand
                per_q[task.id] = job[cand][i].correctness
                effs.append(task_rank[i].get(cand, 0.0))
            return StrategyResult(
                strategy=strategy,
                executor="; ".join(f"{k}->{v}" for k, v in desc.items()),
                quality=sum(per_q.values()) / len(per_q) if per_q else 0.0,
                efficiency=sum(effs) / len(effs) if effs else 0.0,
                per_task_quality=per_q,
            )

        strategies = [result("audit_hire", lambda t: hires.get(t.competency, default))]
        for sname, cname in self.baselines.items():
            strategies.append(result(sname, lambda t, cn=cname: cn))

        return AgenticCaseReport(case=case.name, hires=hires, strategies=strategies)

    def run(self, cases: list[AgenticCase]) -> list[AgenticCaseReport]:
        return [self.run_case(c) for c in cases]
