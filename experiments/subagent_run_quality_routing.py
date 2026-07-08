"""Run 3 (free, real models): does the audit's QUALITY-routing actually fire?

Runs 1-2 showed the cost win but never the quality win, because all frontier models
passed everything. Here we add a deliberately weak-but-cheapest agent, **nano** (haiku
with a fast/terse persona and a minimal, no-edge-case spec), to the pool. nano is real
and mostly competent — but its `merge` returns tuples instead of lists, so it fails the
`intervals` competency while passing `parsing`.

The audit's job: catch that nano is insufficient for intervals and route around it,
while still using cheap nano where it suffices (parsing) — a MIXED team that beats
"always use the cheapest" on quality AND "always use the biggest" on cost.

Held-out: the screening and job use DIFFERENT test instances of the same competency
(standard instance-level split); candidates wrote one function each, seeing no tests.
Solutions are graded in the subprocess sandbox. opus/haiku code is reused from run 2.

    python experiments/subagent_run_quality_routing.py
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.sandbox import run_code_sandboxed
from agent_audit.scoring import Attempt, Effort, discrimination_index, rank_task

PRICE = {"opus": 25.0, "haiku": 5.0, "nano": 1.0}   # output $/Mtok (nano = cheapest tier)
TOKENS = {"opus": 21562, "haiku": 20509, "nano": 20515}
MODELS = ["opus", "haiku", "nano"]

# competency -> function; screening and job are different instances of that function.
COMPETENCY = {"intervals": "merge", "parsing": "decode"}
ENTRY = {"merge": "merge", "decode": "decode"}
SCREEN_TESTS = {
    "merge": [(([[1, 3], [2, 6]],), [[1, 6]]), (([[1, 4], [4, 5]],), [[1, 5]]),
              (([[1, 4], [0, 4]],), [[0, 4]])],
    "decode": [(("3a2b",), "aaabb"), (("1x1y",), "xy")],
}
JOB_TESTS = {   # held-out instances
    "merge": [(([[2, 3], [1, 5], [6, 8]],), [[1, 5], [6, 8]]),
              (([[10, 12], [9, 11]],), [[9, 12]]),
              (([[5, 6], [1, 2], [3, 4]],), [[1, 2], [3, 4], [5, 6]])],
    "decode": [(("2a3b",), "aabbb"), (("12a",), "a" * 12), (("",), "")],
}

# Verbatim solutions. opus/haiku merge+decode reused from run 2; nano is new.
CODE = {
    ("opus", "merge"): "def merge(intervals):\n    if not intervals:\n        return []\n    ordered = sorted(intervals, key=lambda pair: pair[0])\n    merged = [list(ordered[0])]\n    for start, end in ordered[1:]:\n        if start <= merged[-1][1]:\n            merged[-1][1] = max(merged[-1][1], end)\n        else:\n            merged.append([start, end])\n    return merged\n",
    ("haiku", "merge"): "def merge(intervals):\n    if not intervals:\n        return []\n    intervals.sort(key=lambda x: x[0])\n    merged = [intervals[0]]\n    for current in intervals[1:]:\n        last = merged[-1]\n        if current[0] <= last[1]:\n            merged[-1] = [last[0], max(last[1], current[1])]\n        else:\n            merged.append(current)\n    return merged\n",
    ("nano", "merge"): "def merge(intervals):\n    if not intervals:\n        return []\n    intervals.sort()\n    merged = [intervals[0]]\n    for start, end in intervals[1:]:\n        if start <= merged[-1][1]:\n            merged[-1] = (merged[-1][0], max(merged[-1][1], end))\n        else:\n            merged.append((start, end))\n    return merged\n",
    ("opus", "decode"): "def decode(s):\n    result = []\n    i = 0\n    while i < len(s):\n        j = i\n        while s[j].isdigit():\n            j += 1\n        count = int(s[i:j])\n        result.append(s[j] * count)\n        i = j + 1\n    return ''.join(result)\n",
    ("haiku", "decode"): "def decode(s):\n    result = []\n    i = 0\n    n = len(s)\n    while i < n:\n        j = i\n        while j < n and s[j].isdigit():\n            j += 1\n        count = int(s[i:j])\n        char = s[j]\n        result.append(char * count)\n        i = j + 1\n    return ''.join(result)\n",
    ("nano", "decode"): "def decode(s):\n    result = []\n    num = \"\"\n    for char in s:\n        if char.isdigit():\n            num += char\n        else:\n            result.append(char * int(num))\n            num = \"\"\n    return \"\".join(result)\n",
}


def _attempt(model: str, func: str, tests) -> Attempt:
    frac, _, _ = run_code_sandboxed(CODE[(model, func)], ENTRY[func], tests)
    return Attempt(model, frac, Effort(tokens=TOKENS[model],
                                       usd=TOKENS[model] * PRICE[model] / 1e6))


def main() -> int:
    screen = {(m, c): _attempt(m, COMPETENCY[c], SCREEN_TESTS[COMPETENCY[c]])
              for m in MODELS for c in COMPETENCY}
    job = {(m, c): _attempt(m, COMPETENCY[c], JOB_TESTS[COMPETENCY[c]])
           for m in MODELS for c in COMPETENCY}

    print("Correctness (sandbox) — screening / held-out job")
    print(f"  {'competency':<12} " + " ".join(f"{m:>14}" for m in MODELS))
    for c in COMPETENCY:
        cells = " ".join(f"{screen[(m,c)].correctness:>5.2f}/{job[(m,c)].correctness:<5.2f} "
                         .rjust(14) for m in MODELS)
        print(f"  {c:<12} {cells}")

    # Screen -> hire cheapest correct per competency.
    hires = {}
    for c in COMPETENCY:
        ranked = rank_task([screen[(m, c)] for m in MODELS])
        hires[c] = max(ranked, key=ranked.get)
    print("\nHired team (cheapest correct per competency): "
          + ", ".join(f"{c}->{m}" for c, m in hires.items()))

    def strat(name, pick):
        q = [job[(pick(c), c)].correctness for c in COMPETENCY]
        cost = sum(job[(pick(c), c)].effort.usd for c in COMPETENCY)
        return name, sum(q) / len(q), cost

    rows = [strat("audit_hire", lambda c: hires[c])]
    for m in MODELS:
        rows.append(strat(f"always_{m}", lambda c, mm=m: mm))

    print("\nHELD-OUT JOB — quality and cost")
    print(f"  {'strategy':<16} {'quality':>8} {'cost $':>9}")
    for name, q, cost in sorted(rows, key=lambda r: (-r[1], r[2])):
        note = ""
        if name == "always_nano":
            note = "  <- naive 'always cheapest' (fails intervals)"
        if name == "always_opus":
            note = "  <- naive 'always biggest'"
        print(f"  {name:<16} {q:>8.2f} {cost:>9.4f}{note}")

    d = discrimination_index([screen[(m, "intervals")].correctness for m in MODELS])
    print(f"\n  intervals screening discrimination: {d:.2f}  <- >0 means the audit separates them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
