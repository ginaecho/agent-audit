"""Free real-model validation of the AGENTIC harness (no API key spent).

Session models (opus ~opus-4-8, sonnet ~sonnet-5, haiku ~haiku-4-5) each wrote code
via the Claude Code subagent mechanism (2026-07) for a screening audit (merge, decode)
and a HELD-OUT job (insert, evaluate). Their real solutions are graded here in the
subprocess SANDBOX; effort is the real subagent token usage priced by output $/Mtok
(latency was also captured but subagent wall-clock includes scheduling overhead, so it
is shown for reference, not used in the headline efficiency).

Two competencies: intervals (merge/insert), parsing (decode/evaluate). audit_hire hires
the best-per-competency on the screening tasks, then is compared on the held-out job
against always-opus / always-sonnet / always-haiku.

    python experiments/subagent_run_agentic.py
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.sandbox import run_code_sandboxed
from agent_audit.scoring import Attempt, Effort, discrimination_index, rank_task

PRICE = {"opus": 25.0, "sonnet": 15.0, "haiku": 5.0}          # output $/Mtok
MODELS = ["opus", "sonnet", "haiku"]

# Real subagent token totals and wall-clock (ms), captured from the runs.
TOKENS = {
    ("opus", "merge"): 21562, ("sonnet", "merge"): 26985, ("haiku", "merge"): 20509,
    ("opus", "decode"): 21579, ("sonnet", "decode"): 27002, ("haiku", "decode"): 20519,
    ("opus", "insert"): 21584, ("sonnet", "insert"): 27004, ("haiku", "insert"): 20522,
    ("opus", "evaluate"): 21607, ("sonnet", "evaluate"): 27030, ("haiku", "evaluate"): 20536,
}
LATENCY_MS = {
    ("opus", "merge"): 2704, ("sonnet", "merge"): 4713, ("haiku", "merge"): 6096,
    ("opus", "decode"): 2345, ("sonnet", "decode"): 4526, ("haiku", "decode"): 8910,
    ("opus", "insert"): 3692, ("sonnet", "insert"): 7368, ("haiku", "insert"): 9003,
    ("opus", "evaluate"): 5367, ("sonnet", "evaluate"): 3965, ("haiku", "evaluate"): 11107,
}

ENTRYPOINT = {"merge": "merge", "decode": "decode", "insert": "insert", "evaluate": "evaluate"}
HIDDEN = {
    "merge": [(([[1, 3], [2, 6], [8, 10], [15, 18]],), [[1, 6], [8, 10], [15, 18]]),
              (([[1, 4], [4, 5]],), [[1, 5]]), (([[1, 4], [0, 4]],), [[0, 4]]),
              (([[1, 4]],), [[1, 4]])],
    "decode": [(("3a2b",), "aaabb"), (("12a",), "a" * 12), (("",), ""), (("1x1y",), "xy")],
    "insert": [(([[1, 3], [6, 9]], [2, 5]), [[1, 5], [6, 9]]),
               (([[1, 2], [3, 5], [6, 7], [8, 10], [12, 16]], [4, 8]), [[1, 2], [3, 10], [12, 16]]),
               (([], [5, 7]), [[5, 7]]), (([[1, 5]], [2, 3]), [[1, 5]])],
    "evaluate": [(("3+4*2",), 11), (("10-2*3",), 4), (("2*3+4*5",), 26),
                 (("100-10*9",), 10), (("8/2+1",), 5)],
}

# The verbatim code each model wrote.
CODE = {
    ("opus", "merge"): "def merge(intervals):\n    if not intervals:\n        return []\n    ordered = sorted(intervals, key=lambda pair: pair[0])\n    merged = [list(ordered[0])]\n    for start, end in ordered[1:]:\n        if start <= merged[-1][1]:\n            merged[-1][1] = max(merged[-1][1], end)\n        else:\n            merged.append([start, end])\n    return merged\n",
    ("sonnet", "merge"): "def merge(intervals):\n    if not intervals:\n        return []\n    sorted_intervals = sorted(intervals, key=lambda pair: pair[0])\n    merged = [list(sorted_intervals[0])]\n    for start, end in sorted_intervals[1:]:\n        last = merged[-1]\n        if start <= last[1]:\n            last[1] = max(last[1], end)\n        else:\n            merged.append([start, end])\n    return merged\n",
    ("haiku", "merge"): "def merge(intervals):\n    if not intervals:\n        return []\n    intervals.sort(key=lambda x: x[0])\n    merged = [intervals[0]]\n    for current in intervals[1:]:\n        last = merged[-1]\n        if current[0] <= last[1]:\n            merged[-1] = [last[0], max(last[1], current[1])]\n        else:\n            merged.append(current)\n    return merged\n",
    ("opus", "decode"): "def decode(s):\n    result = []\n    i = 0\n    while i < len(s):\n        j = i\n        while s[j].isdigit():\n            j += 1\n        count = int(s[i:j])\n        result.append(s[j] * count)\n        i = j + 1\n    return ''.join(result)\n",
    ("sonnet", "decode"): "def decode(s):\n    result = []\n    i = 0\n    n = len(s)\n    while i < n:\n        j = i\n        while j < n and s[j].isdigit():\n            j += 1\n        count = int(s[i:j])\n        char = s[j]\n        result.append(char * count)\n        i = j + 1\n    return ''.join(result)\n",
    ("haiku", "decode"): "def decode(s):\n    result = []\n    i = 0\n    while i < len(s):\n        count_str = \"\"\n        while i < len(s) and s[i].isdigit():\n            count_str += s[i]\n            i += 1\n        if i < len(s):\n            char = s[i]\n            count = int(count_str) if count_str else 0\n            result.append(char * count)\n            i += 1\n    return ''.join(result)\n",
    ("opus", "insert"): "def insert(intervals, new):\n    result = []\n    start, end = new\n    i, n = 0, len(intervals)\n    while i < n and intervals[i][1] < start:\n        result.append(intervals[i])\n        i += 1\n    while i < n and intervals[i][0] <= end:\n        start = min(start, intervals[i][0])\n        end = max(end, intervals[i][1])\n        i += 1\n    result.append([start, end])\n    while i < n:\n        result.append(intervals[i])\n        i += 1\n    return result\n",
    ("sonnet", "insert"): "def insert(intervals, new):\n    result = []\n    i, n = 0, len(intervals)\n    start, end = new[0], new[1]\n    while i < n and intervals[i][1] < start:\n        result.append(intervals[i])\n        i += 1\n    while i < n and intervals[i][0] <= end:\n        start = min(start, intervals[i][0])\n        end = max(end, intervals[i][1])\n        i += 1\n    result.append([start, end])\n    while i < n:\n        result.append(intervals[i])\n        i += 1\n    return result\n",
    ("haiku", "insert"): "def insert(intervals, new):\n    result = []\n    i = 0\n    start, end = new\n    while i < len(intervals) and intervals[i][1] < start:\n        result.append(intervals[i])\n        i += 1\n    while i < len(intervals) and intervals[i][0] <= end:\n        start = min(start, intervals[i][0])\n        end = max(end, intervals[i][1])\n        i += 1\n    result.append([start, end])\n    while i < len(intervals):\n        result.append(intervals[i])\n        i += 1\n    return result\n",
    ("opus", "evaluate"): "def evaluate(s):\n    tokens = []\n    num = 0\n    for ch in s:\n        if ch.isdigit():\n            num = num * 10 + int(ch)\n        else:\n            tokens.append(num)\n            tokens.append(ch)\n            num = 0\n    tokens.append(num)\n    stack = [tokens[0]]\n    i = 1\n    while i < len(tokens):\n        op = tokens[i]\n        val = tokens[i + 1]\n        if op == '+':\n            stack.append(val)\n        elif op == '-':\n            stack.append(-val)\n        elif op == '*':\n            stack.append(stack.pop() * val)\n        elif op == '/':\n            stack.append(int(stack.pop() / val))\n        i += 2\n    return sum(stack)\n",
    ("sonnet", "evaluate"): "def evaluate(s):\n    tokens = []\n    num = \"\"\n    for ch in s:\n        if ch.isdigit():\n            num += ch\n        else:\n            if num:\n                tokens.append(int(num))\n                num = \"\"\n            if ch in \"+-*/\":\n                tokens.append(ch)\n    if num:\n        tokens.append(int(num))\n    stack = [tokens[0]]\n    i = 1\n    while i < len(tokens):\n        op = tokens[i]\n        val = tokens[i + 1]\n        if op == '+':\n            stack.append(val)\n        elif op == '-':\n            stack.append(-val)\n        elif op == '*':\n            stack.append(stack.pop() * val)\n        elif op == '/':\n            stack.append(int(stack.pop() / val))\n        i += 2\n    return sum(stack)\n",
    ("haiku", "evaluate"): "def evaluate(s):\n    tokens = []\n    current_num = \"\"\n    for char in s:\n        if char.isdigit():\n            current_num += char\n        else:\n            tokens.append(int(current_num))\n            tokens.append(char)\n            current_num = \"\"\n    tokens.append(int(current_num))\n    i = 1\n    while i < len(tokens):\n        if tokens[i] == '*':\n            result = tokens[i-1] * tokens[i+1]\n            tokens = tokens[:i-1] + [result] + tokens[i+2:]\n        elif tokens[i] == '/':\n            result = tokens[i-1] // tokens[i+1]\n            tokens = tokens[:i-1] + [result] + tokens[i+2:]\n        else:\n            i += 2\n    result = tokens[0]\n    i = 1\n    while i < len(tokens):\n        op = tokens[i]\n        num = tokens[i+1]\n        if op == '+':\n            result += num\n        elif op == '-':\n            result -= num\n        i += 2\n    return result\n",
}

SCREEN = {"intervals": "merge", "parsing": "decode"}
JOB = {"intervals": "insert", "parsing": "evaluate"}


def _attempt(model: str, task: str) -> Attempt:
    frac, _, _ = run_code_sandboxed(CODE[(model, task)], ENTRYPOINT[task], HIDDEN[task])
    toks = TOKENS[(model, task)]
    return Attempt(model, frac, Effort(tokens=toks, usd=toks * PRICE[model] / 1e6,
                                       latency_s=LATENCY_MS[(model, task)] / 1000))


def main() -> int:
    # Grade everything in the sandbox.
    grid = {(m, t): _attempt(m, t) for m in MODELS for t in {*SCREEN.values(), *JOB.values()}}

    print("Correctness (sandbox-graded) — 1.00 = all hidden tests passed")
    print(f"  {'task':<10} " + " ".join(f"{m:>8}" for m in MODELS))
    for t in ["merge", "decode", "insert", "evaluate"]:
        print(f"  {t:<10} " + " ".join(f"{grid[(m,t)].correctness:>8.2f}" for m in MODELS))

    # Screen -> hire best per competency (efficiency = correctness-gated, cheapest $).
    hires = {}
    for comp, task in SCREEN.items():
        ranked = rank_task([grid[(m, task)] for m in MODELS])   # cost = usd
        hires[comp] = max(ranked, key=ranked.get)
    print("\nHired (from screening, cheapest correct per competency): "
          + ", ".join(f"{c}->{m}" for c, m in hires.items()))

    # Held-out job: audit_hire routes per competency; baselines fixed.
    job_rank = {comp: rank_task([grid[(m, JOB[comp])] for m in MODELS]) for comp in JOB}

    def strat(name, pick):
        q = [grid[(pick(comp), JOB[comp])].correctness for comp in JOB]
        eff = [job_rank[comp][pick(comp)] for comp in JOB]
        cost = sum(grid[(pick(comp), JOB[comp])].effort.usd for comp in JOB)
        return name, sum(q) / len(q), sum(eff) / len(eff), cost

    rows = [strat("audit_hire", lambda c: hires[c])]
    for m in MODELS:
        rows.append(strat(f"always_{m}", lambda c, mm=m: mm))

    print("\nHELD-OUT JOB (insert, evaluate) — quality, efficiency, cost")
    print(f"  {'strategy':<16} {'quality':>8} {'efficiency':>11} {'cost $':>9}")
    for name, q, eff, cost in sorted(rows, key=lambda r: (-r[1], -r[2])):
        print(f"  {name:<16} {q:>8.2f} {eff:>11.2f} {cost:>9.4f}")

    correctness_spread = discrimination_index(
        [grid[(m, "evaluate")].correctness for m in MODELS])
    print(f"\n  correctness discrimination on the hardest task (evaluate): {correctness_spread:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
