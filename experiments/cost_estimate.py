"""Estimate the cost of the free session-model test runs, priced as if they had
been billed via the Anthropic API. The point: manufacturing a *discriminating*
audit is expensive and low-yield — most runs tie and produce no hiring signal.

Token counts are the subagent totals reported by the harness for each run
(input incl. cached context + output). We can't cleanly split cached-input from
output, so we price at each model's OUTPUT rate = a conservative UPPER BOUND;
the true figure is lower because a large share is cached tool/skill context read
at ~0.1x input rate. These runs were in fact FREE (session models) — this is the
"if you paid for it" estimate.
"""
from agent_audit.providers import PRICING_USD_PER_MTOK

OUT = {  # output $/Mtok
    "opus": PRICING_USD_PER_MTOK["claude-opus-4-8"][1],   # 25
    "sonnet": PRICING_USD_PER_MTOK["claude-sonnet-5"][1],  # 15
    "haiku": PRICING_USD_PER_MTOK["claude-haiku-4-5"][1],  # 5
}

# (label, model, tokens) for every candidate run in THIS session
RUNS = [
    ("union_area", "opus", 21604), ("union_area", "sonnet", 27027), ("union_area", "haiku", 20550),
    ("reason5Q", "opus", 21939), ("reason5Q", "sonnet", 27359), ("reason5Q", "haiku", 20797),
    ("battery_screen", "opus", 21815), ("battery_screen", "sonnet", 27235), ("battery_screen", "haiku", 20700),
    ("battery_held", "opus", 21837), ("battery_held", "sonnet", 27257), ("battery_held", "haiku", 20730),
    ("sweep", "opus", 21754), ("sweep", "opus", 21748), ("sweep", "opus", 21748), ("sweep", "opus", 21748),
    ("sweep", "sonnet", 27174), ("sweep", "sonnet", 27168), ("sweep", "sonnet", 27168), ("sweep", "sonnet", 27168),
    ("sweep", "haiku", 20654), ("sweep", "haiku", 20648), ("sweep", "haiku", 20648), ("sweep", "haiku", 20654),
]

by_model = {"opus": 0, "sonnet": 0, "haiku": 0}
for _, m, t in RUNS:
    by_model[m] += t
total_tokens = sum(by_model.values())
n_runs = len(RUNS)

print(f"Candidate runs this session: {n_runs}")
print(f"Total candidate tokens:      {total_tokens:,}\n")
cost = 0.0
for m in ("opus", "sonnet", "haiku"):
    c = by_model[m] / 1e6 * OUT[m]
    cost += c
    print(f"  {m:6s}: {by_model[m]:>8,} tok  ->  ${c:5.2f}  (@ ${OUT[m]}/Mtok output, upper bound)")
print(f"\nUpper-bound candidate cost (output-priced): ${cost:.2f}")
print(f"Realistic (much is cached input @ ~0.1x): roughly ${cost*0.35:.2f}-${cost*0.6:.2f}")

# Yield: how many distinct hard test DESIGNS actually discriminated?
designs_tried = {
    "8 prior coding problems (calculate, regex, wildcard, valid_paren, "
    "int_to_words, multiply, union_area, ...)": "TIE",
    "10-item prose reasoning battery (single-shot)": "TIE",
    "reliability sweep (repeated sampling)": "DISCRIMINATED",
}
wins = sum(1 for v in designs_tried.values() if v == "DISCRIMINATED")
print(f"\nDiscrimination yield: {wins} win out of ~{len(designs_tried)} distinct hard "
      f"test designs (+ each needed 3 models; the win needed 4x sampling).")

# ---------------------------------------------------------------------------
# THE DOMINANT COST: the strategist (Opus 4.8) rounds to GENERATE the tests.
# The candidate interviews above are the cheap, parallel part. The expensive,
# serial part is Opus 4.8 designing each test, authoring brute-force ground
# truth, grading, and iterating -- once per round, and most rounds TIE.
#
# NOTE: unlike the candidate token counts (measured by the harness), the
# strategist's own main-loop usage is NOT exposed to it, so the per-round token
# model below is an ESTIMATE. Assumptions are explicit so they can be adjusted.
OPUS_IN, OPUS_OUT = PRICING_USD_PER_MTOK["claude-opus-4-8"]   # (5, 25) $/Mtok
OPUS_CACHE = OPUS_IN * 0.1                                     # cache-read ~0.1x input

# Distinct strategist test-generation rounds (design -> dispatch -> grade):
ROUNDS_THIS_SESSION = 4     # union_area, reason5Q, battery(screen+held), reliability sweep
ROUNDS_PRIOR = 12           # ~7 hard coding problems + runs1-3 + coaching + 2 sandbox-debug
ROUNDS_TOTAL = ROUNDS_THIS_SESSION + ROUNDS_PRIOR

# Per-round Opus 4.8 token model (design + ground-truth code + reading candidate
# answers + grading + writing tables), with a mostly-cached growing context:
OUT_PER_ROUND = 4_000       # prompts authored + ground-truth scripts + grading prose
FRESH_IN_PER_ROUND = 18_000 # candidate answers + new tool results read at full input rate
CACHE_IN_PER_ROUND = 90_000 # re-reading the conversation context (cheap cache reads)

def round_cost():
    return (OUT_PER_ROUND * OPUS_OUT
            + FRESH_IN_PER_ROUND * OPUS_IN
            + CACHE_IN_PER_ROUND * OPUS_CACHE) / 1e6

per = round_cost()
# One-time surcharge for the few huge transcript reads pulled into context:
BIG_READ_SURCHARGE = 250_000 * OPUS_IN / 1e6   # ~250k fresh input at $5/Mtok

strat_session = ROUNDS_THIS_SESSION * per + BIG_READ_SURCHARGE
strat_total = ROUNDS_TOTAL * per + BIG_READ_SURCHARGE

print("\n=== Strategist (Opus 4.8) — the main cost (ESTIMATE) ===")
print(f"Per-round Opus 4.8 cost: ~${per:.2f}  "
      f"({OUT_PER_ROUND//1000}k out @${OPUS_OUT} + {FRESH_IN_PER_ROUND//1000}k in @${OPUS_IN} "
      f"+ {CACHE_IN_PER_ROUND//1000}k cache @${OPUS_CACHE:.2f})")
print(f"Rounds this session: {ROUNDS_THIS_SESSION}  ->  ~${strat_session:.2f}")
print(f"Rounds whole project: ~{ROUNDS_TOTAL}  ->  ~${strat_total:.2f}")
print(f"Wasted share: {ROUNDS_TOTAL-1}/{ROUNDS_TOTAL} rounds tied (no signal) "
      f"= ~${(ROUNDS_TOTAL-1)*per:.2f} spent on non-discriminating tests")
print(f"\nCost to find ONE discriminating test = ~{ROUNDS_TOTAL} Opus 4.8 rounds "
      f"~= ${strat_total:.0f}, dwarfing the ${cost:.0f} of candidate interviews per session.")
