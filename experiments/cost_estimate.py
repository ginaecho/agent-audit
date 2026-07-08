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
