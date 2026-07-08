"""Offline test: audit-hire beats single-model baselines on executable held-out tasks."""

from __future__ import annotations

from agent_audit.agentic_harness import AgenticCase, AgenticHarness
from agent_audit.execution import CodingTask
from agent_audit.providers import MockProvider

# Two competencies; two specialists that each ace one and fail the other, plus a
# correct-but-verbose generalist (higher token cost -> lower efficiency).
_ADD_OK = "def add(a, b):\n    return a + b\n"
_ADD_BAD = "def add(a, b):\n    return a - b\n"
_MUL_OK = "def mul(a, b):\n    return a * b\n"
_MUL_BAD = "def mul(a, b):\n    return a + b\n"
_VERBOSE = "# a very long, rambling, wasteful preamble " * 8 + "\n"


def _fence(code):
    return f"```python\n{code}```"


def _add_specialist(p, s):
    return _fence(_ADD_OK if "`add`" in p else _MUL_BAD)


def _mul_specialist(p, s):
    return _fence(_MUL_OK if "`mul`" in p else _ADD_BAD)


def _generalist(p, s):  # correct at both, but wasteful -> costlier -> less efficient
    return _fence((_VERBOSE + (_ADD_OK if "`add`" in p else _MUL_OK)))


def _tasks(entry, comp, tests):
    return CodingTask(id=f"{entry}_{comp}", competency=comp, entrypoint=entry,
                      prompt=f"Write {entry}(a, b).", hidden_tests=tests)


CASE = AgenticCase(
    name="add_mul",
    requirement="an arithmetic coding agent",
    screening=[
        _tasks("add", "addition", [((2, 3), 5), ((0, 0), 0)]),
        _tasks("mul", "multiplication", [((2, 3), 6), ((4, 5), 20)]),
    ],
    job=[
        _tasks("add", "addition", [((10, 5), 15), ((-2, 2), 0)]),
        _tasks("mul", "multiplication", [((3, 3), 9), ((7, 0), 0)]),
    ],
)


def _harness():
    candidates = [
        MockProvider("add_spec", _add_specialist),
        MockProvider("mul_spec", _mul_specialist),
        MockProvider("generalist", _generalist),
    ]
    return AgenticHarness(candidates, baselines={
        "always_add_spec": "add_spec",
        "always_mul_spec": "mul_spec",
        "always_generalist": "generalist",
    })


def test_audit_hires_the_right_specialist_per_competency():
    report = _harness().run_case(CASE)
    assert report.hires == {"addition": "add_spec", "multiplication": "mul_spec"}


def test_audit_hire_beats_single_specialist_on_quality():
    report = _harness().run_case(CASE)
    by = {s.strategy: s for s in report.strategies}
    assert by["audit_hire"].quality == 1.0                    # aces both competencies
    assert by["always_add_spec"].quality == 0.5              # fails the multiplication job
    assert by["always_mul_spec"].quality == 0.5              # fails the addition job
    assert by["audit_hire"].quality > by["always_add_spec"].quality


def test_audit_hire_matches_generalist_quality_but_beats_it_on_efficiency():
    report = _harness().run_case(CASE)
    by = {s.strategy: s for s in report.strategies}
    assert by["always_generalist"].quality == 1.0            # also correct on both...
    assert by["audit_hire"].efficiency > by["always_generalist"].efficiency  # ...but costlier
