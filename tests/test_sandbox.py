"""Tests for the subprocess sandbox (safe execution of untrusted code)."""

from __future__ import annotations

from agent_audit.execution import CodingTask, solve_coding_task
from agent_audit.providers import MockProvider
from agent_audit.sandbox import run_code_sandboxed

TESTS = [((2, 3), 5), ((-1, 1), 0)]


def test_correct_code_passes_in_sandbox():
    frac, detail, latency = run_code_sandboxed("def add(a, b):\n    return a + b", "add", TESTS)
    assert frac == 1.0 and "passed" in detail and latency >= 0.0


def test_wrong_code_fails_in_sandbox():
    frac, detail, _ = run_code_sandboxed("def add(a, b):\n    return a - b", "add", TESTS)
    assert frac == 0.0 and "expected" in detail


def test_infinite_loop_is_killed_by_timeout():
    frac, detail, latency = run_code_sandboxed(
        "def add(a, b):\n    while True:\n        pass", "add", TESTS, timeout_s=1)
    assert frac == 0.0 and "timed out" in detail
    assert latency < 3.0  # killed near the 1s deadline, not hung forever


def test_imports_are_blocked():
    frac, detail, _ = run_code_sandboxed(
        "import os\ndef add(a, b):\n    return os.getpid()", "add", TESTS)
    assert frac == 0.0 and ("did not load" in detail or "__import__" in detail)


def test_solve_coding_task_with_sandbox_runner():
    task = CodingTask(id="add", competency="coding", entrypoint="add",
                      prompt="Write add(a, b) returning a+b.", hidden_tests=TESTS)
    ace = MockProvider("ace", lambda p, s: "```python\ndef add(a, b):\n    return a + b\n```")
    attempt = solve_coding_task(ace, task, runner=run_code_sandboxed)
    assert attempt.correctness == 1.0 and attempt.effort.steps == 1
