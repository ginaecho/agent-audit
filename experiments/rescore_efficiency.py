"""Re-score run 1 with efficiency: does 'cheapest correct' discriminate where
correctness did not?

Uses the SAME real-model answers from `subagent_run_claim_verification.py` (all three
tiers were correct on every held-out job task), now scored by correctness x cost.
Effort is the tokens each real model spent, times its output price — so a correct
answer in fewer, cheaper tokens scores higher. The token counts are the observed
subagent totals (rough: they include some scaffolding overhead), so read this as
directional; a clean run instruments per-task model tokens directly.

    python experiments/rescore_efficiency.py
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.scoring import (
    Attempt,
    Effort,
    discrimination_index,
    efficiency_leaderboard,
    is_discriminating,
)
from agent_audit.providers import PRICING_USD_PER_MTOK

# Observed real-model usage on the held-out job (total subagent tokens; rough).
JOB_TOKENS = {"opus": 22030, "sonnet": 27453, "haiku": 20840}
# Map the 3 tiers to concrete model IDs for pricing (output $/Mtok).
PRICE = {
    "opus": PRICING_USD_PER_MTOK["claude-opus-4-8"][1],    # 25
    "sonnet": PRICING_USD_PER_MTOK["claude-sonnet-5"][1],  # 15
    "haiku": PRICING_USD_PER_MTOK["claude-haiku-4-5"][1],  # 5
}

# All three were CORRECT on every held-out job task (correctness 1.0 each) — this is
# exactly the case that gave a 3-way tie under a correctness-only rubric.
CORRECTNESS = {"opus": 1.0, "sonnet": 1.0, "haiku": 1.0}


def main() -> int:
    # One combined "solve the job" task per candidate: correctness + what it cost.
    attempts = [
        Attempt(
            candidate=c,
            correctness=CORRECTNESS[c],
            effort=Effort(tokens=JOB_TOKENS[c], usd=JOB_TOKENS[c] * PRICE[c] / 1e6),
        )
        for c in ("opus", "sonnet", "haiku")
    ]

    correctness_scores = [CORRECTNESS[c] for c in ("opus", "sonnet", "haiku")]
    eff = efficiency_leaderboard([attempts])
    eff_scores = list(eff.values())

    print("Held-out job — correctness-only vs efficiency-weighted\n")
    print(f"  {'candidate':<10} {'correct':>8} {'tokens':>8} {'cost $':>9} {'efficiency':>11}")
    for c in ("opus", "sonnet", "haiku"):
        a = next(x for x in attempts if x.candidate == c)
        print(f"  {c:<10} {a.correctness:>8.2f} {a.effort.tokens:>8} "
              f"{a.effort.usd:>9.4f} {eff[c]:>11.2f}")

    print(f"\n  discrimination (correctness-only): {discrimination_index(correctness_scores):.2f}"
          "   <- 0.00 = no hiring signal (the 3-way tie)")
    print(f"  discrimination (efficiency)       : {discrimination_index(eff_scores):.2f}"
          f"   <- separated;  worth-hiring={is_discriminating(eff_scores)}")

    winner = max(eff, key=eff.get)
    print(f"\n  => efficiency hires: {winner}  (correct AND cheapest path)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
