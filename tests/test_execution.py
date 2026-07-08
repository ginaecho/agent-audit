"""Tests for executable/agentic audit tasks (Stage 3)."""

from __future__ import annotations

from agent_audit.execution import (
    CodingTask,
    extract_code,
    run_code,
    solve_coding_task,
)
from agent_audit.providers import MockProvider
from agent_audit.scoring import AGENTIC_WEIGHTS, rank_task

_TASK = CodingTask(
    id="add", competency="coding", entrypoint="add",
    prompt="Write add(a, b) returning a+b.",
    hidden_tests=[((2, 3), 5), ((-1, 1), 0)],
)


def test_extract_code_handles_fences():
    assert extract_code("```python\ndef f():\n    return 1\n```").startswith("def f")
    assert extract_code("def g(): return 2") == "def g(): return 2"


def test_run_code_passes_correct_and_flags_wrong():
    frac, detail, latency = run_code("def add(a, b):\n    return a + b\n", "add",
                                     _TASK.hidden_tests)
    assert frac == 1.0 and "passed" in detail and latency >= 0.0
    frac, detail, _ = run_code("def add(a, b):\n    return a - b\n", "add",
                               _TASK.hidden_tests)
    assert frac < 1.0 and "expected" in detail


def test_run_code_handles_broken_code():
    frac, detail, _ = run_code("def add(a, b):\n    return a +", "add", _TASK.hidden_tests)
    assert frac == 0.0 and "did not load" in detail
    frac, detail, _ = run_code("x = 1", "add", _TASK.hidden_tests)
    assert frac == 0.0 and "no callable" in detail


def _fence(code):
    return f"```python\n{code}\n```"


def test_ace_solves_in_one_step():
    ace = MockProvider("ace", lambda p, s: _fence("def add(a, b):\n    return a + b"))
    attempt = solve_coding_task(ace, _TASK)
    assert attempt.correctness == 1.0
    assert attempt.effort.steps == 1


def test_grinder_needs_a_retry_then_passes():
    def grinder(prompt, system=None):
        if "It failed" in prompt:                        # retry: fix it
            return _fence("def add(a, b):\n    return a + b")
        return _fence("def add(a, b):\n    return a - b")  # first try: buggy
    attempt = solve_coding_task(MockProvider("grinder", grinder), _TASK)
    assert attempt.correctness == 1.0
    assert attempt.effort.steps == 2                     # one failure, one fix


def test_novice_never_greens_and_scores_zero_on_efficiency():
    novice = MockProvider("novice", lambda p, s: _fence("def add(a, b):\n    return a - b"))
    ace = MockProvider("ace", lambda p, s: _fence("def add(a, b):\n    return a + b"))
    a_novice = solve_coding_task(novice, _TASK, max_steps=3)
    a_ace = solve_coding_task(ace, _TASK)
    assert a_novice.correctness < 1.0
    assert a_novice.effort.steps == 3                    # burned every retry
    scores = rank_task([a_ace, a_novice], weights=AGENTIC_WEIGHTS)
    assert scores["ace"] == 1.0
    assert scores["novice"] == 0.0                       # wrong -> zero, cheap or not
