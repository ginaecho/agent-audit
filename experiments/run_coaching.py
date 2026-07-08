"""Run the audit -> coach -> improve -> re-audit loop against real Claude models.

    export ANTHROPIC_API_KEY=sk-ant-...
    python experiments/run_coaching.py [--candidate claude-haiku-4-5]

Demonstrates the claim that the audit is a *coaching instrument*, not just a gate:

1. audit the candidate (default: the weakest, claude-haiku-4-5) on a requirement;
2. the Coach turns its failures into an ImprovementPlan (advice written by the
   strategist model from the concrete failure evidence);
3. the plan's skill_text is attached to the candidate (SkilledProvider) — this is
   "agent A -> agent B by improving its skills";
4. the SAME audit is re-run on agent B, so the uplift is measured by the very
   instrument that prescribed it.

No Fable 5 anywhere: strategist/coach = opus-4-8, judge = opus-4-7.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.coach import Coach
from agent_audit.pipeline import AuditPipeline
from agent_audit.providers import (
    JUDGE_MODEL,
    STRATEGIST_MODEL,
    AnthropicProvider,
    SkilledProvider,
)
from experiments.cases import CASE_POLICY


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="claude-haiku-4-5")
    parser.add_argument("--out", default="runs/coaching_report.json")
    args = parser.parse_args()

    strategist = AnthropicProvider(STRATEGIST_MODEL, effort="high", max_tokens=8000,
                                   name=f"strategist:{STRATEGIST_MODEL}")
    judge = AnthropicProvider(JUDGE_MODEL, effort="medium", name=f"judge:{JUDGE_MODEL}")
    pipeline = AuditPipeline(strategist=strategist, judge=judge)

    agent_a = AnthropicProvider(args.candidate, name=f"{args.candidate} (agent A)")

    # 1. Author the audit once, screen agent A.
    requirement = CASE_POLICY.requirement
    audit = pipeline.strategist.design_audit(requirement,
                                             competencies=CASE_POLICY.competencies)
    run_a = pipeline.run(requirement, [agent_a], audit=audit)
    report_a = run_a.reports[0]

    # 2-3. Coach A into B using the strategist as the advice writer.
    coach = Coach(coach=strategist)
    plan = coach.improvement_plan(audit, report_a)
    print(plan.summary())
    print("\n--- skill attached to agent B ---\n" + (plan.skill_text or "(none needed)"))

    agent_b = SkilledProvider(agent_a, plan.skill_text,
                              name=f"{args.candidate} (agent B, coached)")

    # 4. Re-run the SAME audit on B (re-certification path — no fresh exam).
    run_b = pipeline.run(requirement, [agent_b], audit=audit)
    report_b = run_b.reports[0]

    print("\n=== uplift measured by the same audit ===")
    print(f"{'competency':<26} {'agent A':>8} {'agent B':>8}")
    for comp in audit.competencies:
        a = report_a.competency_scores.get(comp, 0.0)
        b = report_b.competency_scores.get(comp, 0.0)
        print(f"{comp:<26} {a:>8.2f} {b:>8.2f}")
    print(f"{'OVERALL':<26} {report_a.overall_score:>8.2f} {report_b.overall_score:>8.2f}")
    print(f"hired: A={report_a.hired}  B={report_b.hired}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({
            "requirement": requirement,
            "audit": audit.to_dict(),
            "agent_a": report_a.to_dict(),
            "improvement_plan": plan.to_dict(),
            "agent_b": report_b.to_dict(),
        }, fh, indent=2, default=str)
    print(f"\nFull report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
