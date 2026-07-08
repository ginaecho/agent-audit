"""Stages 2 + 3 together, fully offline: adaptive design + executable-task scoring.

The strategist escalates an executable coding audit until the candidates SEPARATE
(Stage 2), then the hired decision is made on who reaches green in the fewest steps,
tokens, and least wall-clock time (Stage 3, speed folded into efficiency).

Candidates are mock coding agents of deliberately different skill:
  * ace     — writes correct code in one shot
  * grinder — first attempt has an edge-case bug; fixes it after seeing the failure
  * novice  — misses the edge case and never fixes it

Round 0 (easy task) can't tell them apart — all pass in one step. The strategist
hardens; round 1 (a task with sorting/adjacency edges) separates them cleanly.

    python experiments/run_agentic_audit.py
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.adaptive import design_discriminating
from agent_audit.execution import CodingTask, run_coding_audit
from agent_audit.providers import MockProvider
from agent_audit.scoring import AGENTIC_WEIGHTS, efficiency_leaderboard, rank_task

# --- Tasks the (mock) strategist authors, escalating in difficulty ------------
EASY = CodingTask(
    id="easy_add", competency="coding", entrypoint="add",
    prompt="Write a function add(a, b) that returns the sum of a and b.",
    hidden_tests=[((2, 3), 5), ((-1, 1), 0), ((0, 0), 0)],
)
HARD = CodingTask(
    id="hard_merge", competency="coding", entrypoint="merge",
    prompt=("Write merge(intervals): given a list of [start, end] intervals (in any "
            "order), return the list of merged, non-overlapping intervals sorted by "
            "start. Treat touching intervals like [1,4] and [4,5] as overlapping."),
    hidden_tests=[
        (([[1, 3], [2, 6], [8, 10], [15, 18]],), [[1, 6], [8, 10], [15, 18]]),
        (([[1, 4], [4, 5]],), [[1, 5]]),        # adjacency edge
        (([[1, 4], [0, 4]],), [[0, 4]]),        # unsorted-input edge
    ],
)

_ADD = "def add(a, b):\n    return a + b\n"
_MERGE_CORRECT = (
    "def merge(intervals):\n"
    "    intervals = sorted(intervals)\n"
    "    out = []\n"
    "    for s, e in intervals:\n"
    "        if out and s <= out[-1][1]:\n"
    "            out[-1][1] = max(out[-1][1], e)\n"
    "        else:\n"
    "            out.append([s, e])\n"
    "    return out\n"
)
_MERGE_BUGGY = (  # forgets to sort -> fails the unsorted-input edge
    "def merge(intervals):\n"
    "    out = []\n"
    "    for s, e in intervals:\n"
    "        if out and s <= out[-1][1]:\n"
    "            out[-1][1] = max(out[-1][1], e)\n"
    "        else:\n"
    "            out.append([s, e])\n"
    "    return out\n"
)


def _fence(code: str) -> str:
    return f"```python\n{code}```"


def _agent(skill: str):
    def respond(prompt: str, system: str | None) -> str:
        retry = "It failed" in prompt
        if "add(a, b)" in prompt:
            return _fence(_ADD)                      # everyone can do the easy one
        # hard 'merge' task:
        if skill == "ace":
            return _fence(_MERGE_CORRECT)            # correct first try
        if skill == "grinder":
            return _fence(_MERGE_CORRECT if retry else _MERGE_BUGGY)  # fixes on feedback
        return _fence(_MERGE_BUGGY)                  # novice: buggy, never fixes
    return MockProvider(skill, respond)


def _transpose(by_cand: dict[str, list]) -> list[list]:
    names = list(by_cand)
    n_tasks = len(next(iter(by_cand.values())))
    return [[by_cand[name][i] for name in names] for i in range(n_tasks)]


def main() -> int:
    candidates = [_agent("ace"), _agent("grinder"), _agent("novice")]

    def generate(round_index: int, feedback: str | None):
        # The strategist hardens: easy first, then a task with real edges.
        return [EASY] if round_index == 0 else [HARD]

    def screen(tasks):
        by_cand = run_coding_audit(candidates, tasks)
        return efficiency_leaderboard(_transpose(by_cand), weights=AGENTIC_WEIGHTS)

    result = design_discriminating(generate, screen, max_rounds=3, min_discrimination=0.15)
    print(result.summary())

    # Final hiring decision on the chosen (discriminating) exam.
    chosen_tasks = result.exam   # the exam the loop selected (do not regenerate)
    by_cand = run_coding_audit(candidates, chosen_tasks)
    attempts_by_task = _transpose(by_cand)

    print("\nExecutable audit — shortest path to green (chosen exam)")
    print(f"  {'candidate':<10} {'correct':>8} {'steps':>6} {'tokens':>7} {'efficiency':>11}")
    task_scores = rank_task(attempts_by_task[0], weights=AGENTIC_WEIGHTS)
    for name, attempts in by_cand.items():
        a = attempts[0]
        print(f"  {name:<10} {a.correctness:>8.2f} {a.effort.steps:>6} "
              f"{a.effort.tokens:>7} {task_scores[name]:>11.2f}")

    hire = max(task_scores, key=task_scores.get)
    print(f"\n  => hire: {hire}  (reaches green correctly in the fewest steps/tokens/time)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
