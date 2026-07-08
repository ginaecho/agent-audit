"""The full agentic pipeline, offline: strategist AUTHORS the tasks, candidates run
SANDBOXED, adaptive loop hardens until they separate, hire by shortest-path-to-green.

This combines every piece:
  * the strategist authors executable coding tasks + hidden tests
    (Strategist.design_coding_audit) — here a mock strategist that escalates when told
    to harden; a real opus-4-8 would generate these from the requirement;
  * candidate code runs in the subprocess sandbox (sandbox.run_code_sandboxed), so
    untrusted model code is isolated (CPU/mem/file rlimits + timeout + no imports);
  * the adaptive loop (Stage 2) hardens the authored audit until candidates separate;
  * hiring is by efficiency incl. speed (Stage 3).

    python experiments/run_authored_agentic_audit.py
"""

from __future__ import annotations

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.adaptive import design_discriminating
from agent_audit.execution import run_coding_audit
from agent_audit.providers import MockProvider
from agent_audit.sandbox import run_code_sandboxed
from agent_audit.scoring import AGENTIC_WEIGHTS, efficiency_leaderboard, rank_task
from agent_audit.strategist import Strategist

REQUIREMENT = ("A utility-coding agent for list/interval processing: it must write "
               "small, correct Python functions, including tricky edge cases.")

# --- Mock strategist: authors an easy task, then a hard one once told to harden ---
_EASY_AUDIT = {
    "summary": "warm-up", "competencies": ["coding"],
    "tasks": [{"competency": "coding", "entrypoint": "add",
               "prompt": "Write a function add(a, b) that returns the sum of a and b.",
               "hidden_tests": [{"args": [2, 3], "expected": 5},
                                {"args": [-1, 1], "expected": 0}]}],
}
_HARD_AUDIT = {
    "summary": "interval merging with edges", "competencies": ["coding"],
    "tasks": [{"competency": "coding", "entrypoint": "merge",
               "prompt": ("Write merge(intervals): given a list of [start, end] intervals "
                          "in any order, return merged non-overlapping intervals sorted by "
                          "start. Touching intervals like [1,4] and [4,5] count as "
                          "overlapping."),
               "hidden_tests": [
                   {"args": [[[1, 3], [2, 6], [8, 10], [15, 18]]], "expected": [[1, 6], [8, 10], [15, 18]]},
                   {"args": [[[1, 4], [4, 5]]], "expected": [[1, 5]]},
                   {"args": [[[1, 4], [0, 4]]], "expected": [[0, 4]]}]}],
}


def _strategist_responder(prompt: str, system: str | None) -> str:
    hardened = "FAILED TO DISCRIMINATE" in prompt
    return json.dumps(_HARD_AUDIT if hardened else _EASY_AUDIT)


# --- Mock coding agents of different skill ------------------------------------
_ADD = "def add(a, b):\n    return a + b\n"
_MERGE_OK = ("def merge(intervals):\n    intervals = sorted(intervals)\n    out = []\n"
             "    for s, e in intervals:\n        if out and s <= out[-1][1]:\n"
             "            out[-1][1] = max(out[-1][1], e)\n        else:\n"
             "            out.append([s, e])\n    return out\n")
_MERGE_BUG = ("def merge(intervals):\n    out = []\n    for s, e in intervals:\n"
              "        if out and s <= out[-1][1]:\n            out[-1][1] = max(out[-1][1], e)\n"
              "        else:\n            out.append([s, e])\n    return out\n")


def _agent(skill: str):
    def respond(prompt: str, system: str | None) -> str:
        retry = "It failed" in prompt
        if "add(a, b)" in prompt:
            return f"```python\n{_ADD}```"
        if skill == "ace":
            return f"```python\n{_MERGE_OK}```"
        if skill == "grinder":
            return f"```python\n{_MERGE_OK if retry else _MERGE_BUG}```"
        return f"```python\n{_MERGE_BUG}```"
    return MockProvider(skill, respond)


def _transpose(by_cand):
    names = list(by_cand)
    n = len(next(iter(by_cand.values())))
    return [[by_cand[name][i] for name in names] for i in range(n)]


def main() -> int:
    strategist = Strategist(MockProvider("strategist(opus-mock)", _strategist_responder))
    candidates = [_agent("ace"), _agent("grinder"), _agent("novice")]

    def generate(round_index, feedback):
        audit = strategist.design_coding_audit(
            REQUIREMENT, competencies=["coding"], harden_feedback=feedback,
            version=round_index + 1)
        print(f"  [strategist authored round {round_index}: "
              f"{[t.entrypoint for t in audit.tasks]}]")
        return audit.tasks

    def screen(tasks):
        by_cand = run_coding_audit(candidates, tasks, runner=run_code_sandboxed)  # SANDBOXED
        return efficiency_leaderboard(_transpose(by_cand), weights=AGENTIC_WEIGHTS)

    print("Adaptive design over strategist-authored, sandbox-run coding tasks:")
    result = design_discriminating(generate, screen, max_rounds=3, min_discrimination=0.15)
    print(result.summary())

    chosen = result.exam   # the discriminating exam the loop selected (do not regenerate)
    by_cand = run_coding_audit(candidates, chosen, runner=run_code_sandboxed)
    scores = rank_task(_transpose(by_cand)[0], weights=AGENTIC_WEIGHTS)
    print("\nFinal hire (authored task, sandboxed execution):")
    print(f"  {'candidate':<10} {'correct':>8} {'steps':>6} {'efficiency':>11}")
    for name, attempts in by_cand.items():
        a = attempts[0]
        print(f"  {name:<10} {a.correctness:>8.2f} {a.effort.steps:>6} {scores[name]:>11.2f}")
    print(f"\n  => hire: {max(scores, key=scores.get)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
