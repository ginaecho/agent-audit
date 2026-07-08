"""Executable / agentic audit tasks — "shortest path to green" scoring.

Text Q&A gives a mild efficiency signal. An *executable* task gives a sharp one: the
item is "write a function that passes these hidden tests," and the candidate runs in
an agent loop — write code, run it, read the error, fix, repeat — until the hidden
tests pass or it gives up. The score rewards **who reaches green in the fewest steps,
fewest tokens, and least wall-clock time** (speed). A strong agent writes a correct
function in one shot; a weak one flails across several failed attempts or never
passes. That is maximal discrimination, and it is exactly the trait being hired for:
capability per unit cost.

The same shape covers **MCP / tool-using** candidates — give the candidate a
`FunctionProvider` that calls tools and increments a tool-call counter; `Effort`
already carries `tool_calls`, and the scoring already weights it.

Security note: `run_code` execs candidate code in-process with a restricted builtin
set — fine for this prototype and for the offline mock agents in the tests. For real,
untrusted model-written code, run it in a subprocess sandbox / container with CPU,
memory, and filesystem limits. The interface (code in, pass-fraction + latency out)
does not change.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .providers import Provider
from .scoring import Attempt, Effort

# A conservative allowlist of builtins available to candidate code.
_SAFE_BUILTINS = {
    k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
    for k in (
        "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
        "int", "len", "list", "map", "max", "min", "range", "reversed", "round", "set",
        "sorted", "str", "sum", "tuple", "zip", "True", "False", "None", "print",
        "isinstance", "ValueError", "TypeError", "IndexError", "KeyError", "Exception",
    )
}


@dataclass
class CodingTask:
    """An executable audit item: define ``entrypoint`` so it passes ``hidden_tests``.

    ``hidden_tests`` are (args_tuple, expected_return) pairs the candidate never sees —
    it only sees ``prompt`` (and, on retries, the failure of the tests it ran).
    """

    id: str
    competency: str
    prompt: str
    entrypoint: str
    hidden_tests: list[tuple[tuple, Any]]
    weight: float = 1.0


def extract_code(text: str) -> str:
    """Pull a python code block out of a model response, else return the text."""
    fence = re.search(r"```(?:python)?\s*(.+?)```", text, re.DOTALL)
    return (fence.group(1) if fence else text).strip()


def run_code(
    code: str,
    entrypoint: str,
    hidden_tests: list[tuple[tuple, Any]],
) -> tuple[float, str, float]:
    """Exec ``code``, run the hidden tests, return (pass_fraction, detail, exec_seconds)."""
    ns: dict[str, Any] = {}
    t0 = time.perf_counter()
    try:
        exec(code, {"__builtins__": _SAFE_BUILTINS}, ns)  # noqa: S102 (see security note)
    except Exception as exc:  # syntax/name/etc.
        return 0.0, f"code did not load: {type(exc).__name__}: {exc}", time.perf_counter() - t0
    fn = ns.get(entrypoint)
    if not callable(fn):
        return 0.0, f"no callable named '{entrypoint}' was defined", time.perf_counter() - t0

    passed = 0
    first_fail = ""
    for args, expected in hidden_tests:
        try:
            got = fn(*args)
        except Exception as exc:
            if not first_fail:
                first_fail = f"{entrypoint}{args!r} raised {type(exc).__name__}: {exc}"
            continue
        if got == expected:
            passed += 1
        elif not first_fail:
            first_fail = f"{entrypoint}{args!r} returned {got!r}, expected {expected!r}"
    latency = time.perf_counter() - t0
    total = len(hidden_tests) or 1
    detail = "all hidden tests passed" if passed == total else f"{passed}/{total} passed; {first_fail}"
    return passed / total, detail, latency


def _estimate_tokens(provider: Provider, text_in: str, text_out: str) -> int:
    """Prefer the provider's own usage delta; fall back to a length estimate."""
    return max(1, (len(text_in) + len(text_out)) // 4)


def solve_coding_task(
    candidate: Provider,
    task: CodingTask,
    *,
    max_steps: int = 4,
    system: str | None = None,
) -> Attempt:
    """Run ``candidate`` as an agent on ``task``: write -> run -> fix, until green.

    Returns an ``Attempt`` whose ``correctness`` is the best pass-fraction reached and
    whose ``Effort`` records the path: total tokens, number of steps (write/run
    cycles), and cumulative wall-clock time (generation + execution = "speed").
    """
    instruction = (
        f"{task.prompt}\n\nDefine a Python function named `{task.entrypoint}`. "
        "Return ONLY a ```python fenced code block — no prose."
    )
    prompt = instruction
    steps = 0
    tokens = 0
    latency = 0.0
    best = 0.0
    for _ in range(max_steps):
        steps += 1
        t0 = time.perf_counter()
        out = candidate.complete(prompt, system=system)
        gen_latency = time.perf_counter() - t0
        tokens += _estimate_tokens(candidate, prompt, out)
        code = extract_code(out)
        frac, detail, exec_latency = run_code(code, task.entrypoint, task.hidden_tests)
        latency += gen_latency + exec_latency
        best = max(best, frac)
        if frac >= 1.0:
            break
        prompt = (
            f"{instruction}\n\nYour previous attempt was:\n```python\n{code}\n```\n"
            f"It failed: {detail}\nFix the function and return the corrected fenced block."
        )
    return Attempt(candidate=candidate.name, correctness=best,
                   effort=Effort(tokens=tokens, steps=steps, latency_s=latency))


def run_coding_audit(
    candidates: list[Provider],
    tasks: list[CodingTask],
    *,
    max_steps: int = 4,
    system: str | None = None,
) -> dict[str, list[Attempt]]:
    """Every candidate attempts every task. Returns candidate -> per-task Attempts."""
    return {
        c.name: [solve_coding_task(c, t, max_steps=max_steps, system=system) for t in tasks]
        for c in candidates
    }
