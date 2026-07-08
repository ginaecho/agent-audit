"""Run the audit-vs-baselines experiment against real Claude models.

    export ANTHROPIC_API_KEY=sk-ant-...     # or `ant auth login`
    python experiments/run_harness.py [--cases structured_extraction ...]

Model policy (fixed for this study — no Fable 5 anywhere):

    strategist  claude-opus-4-8   authors the audit  (most capable, not a candidate)
    judge       claude-opus-4-7   grades llm_judge checks (not a candidate either)
    candidates  claude-opus-4-6, claude-sonnet-4-6, claude-sonnet-5, claude-haiku-4-5

Baselines the audit-hired team is compared against on held-out job tasks:

    biggest_model     always claude-opus-4-6   (priciest candidate tier)
    leaderboard_pick  always claude-sonnet-5   (top public-leaderboard pick)
    cheapest_model    always claude-haiku-4-5  (cost floor)

Output: a quality+cost table per case and a JSON artifact under runs/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.grader import Grader
from agent_audit.harness import Harness
from agent_audit.pipeline import AuditPipeline
from agent_audit.providers import (
    CANDIDATE_MODELS,
    JUDGE_MODEL,
    STRATEGIST_MODEL,
    AnthropicProvider,
)
from experiments.cases import ALL_CASES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=None,
                        help="subset of case names to run (default: all)")
    parser.add_argument("--out", default="runs/harness_report.json")
    args = parser.parse_args()

    cases = ALL_CASES if not args.cases else [c for c in ALL_CASES if c.name in args.cases]
    if not cases:
        parser.error(f"no matching cases; available: {[c.name for c in ALL_CASES]}")

    strategist = AnthropicProvider(STRATEGIST_MODEL, effort="high", max_tokens=8000,
                                   name=f"strategist:{STRATEGIST_MODEL}")
    judge = AnthropicProvider(JUDGE_MODEL, effort="medium", name=f"judge:{JUDGE_MODEL}")
    candidates = [AnthropicProvider(m) for m in CANDIDATE_MODELS]
    by_model = {p.model: p for p in candidates}

    pipeline = AuditPipeline(strategist=strategist, judge=judge)
    harness = Harness(
        pipeline=pipeline,
        grader=pipeline.grader,           # same judge grades audit and job tasks
        candidates=candidates,
        baselines={
            "biggest_model": by_model["claude-opus-4-6"],
            "leaderboard_pick": by_model["claude-sonnet-5"],
            "cheapest_model": by_model["claude-haiku-4-5"],
        },
    )

    report = harness.run(cases)
    print(report.summary())

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, default=str)
    print(f"\nFull report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
