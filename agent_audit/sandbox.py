"""Subprocess sandbox for running untrusted, model-written code.

``execution.run_code`` execs in-process — fast, fine for trusted/mock candidates and
the test suite. For *real* model-written code you want isolation: this runs the code
in a separate ``python -I`` process with (on Unix) CPU-time, memory, file-size, and
process-count rlimits plus a hard wall-clock timeout, a scrubbed environment, and the
same restricted-builtins namespace (no ``open``, no ``__import__``). Same signature as
``run_code`` — ``(code, entrypoint, hidden_tests) -> (pass_fraction, detail, seconds)``
— so ``solve_coding_task(..., runner=run_code_sandboxed)`` is a drop-in swap.

Defense in depth, not a security guarantee. rlimits + restricted builtins stop the
common failure modes (infinite loops, memory bombs, importing ``os``/``socket``,
file writes). They do **not** block all network egress or every escape — for hostile
code at scale, run this inside a container / gVisor / seccomp jail with no network.
Windows lacks ``resource``; there you get the subprocess + timeout but not rlimits.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

try:
    import resource  # Unix only
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore

# Names the sandboxed code may use. Deliberately excludes open/import/eval/exec/etc.
_SAFE_NAMES = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
    "int", "len", "list", "map", "max", "min", "range", "reversed", "round", "set",
    "sorted", "str", "sum", "tuple", "zip", "True", "False", "None", "print",
    "isinstance", "ValueError", "TypeError", "IndexError", "KeyError", "Exception",
    "ZeroDivisionError", "StopIteration", "frozenset", "bytes", "ord", "chr", "repr",
]

_DRIVER = r"""
import json, sys, builtins
safe = {n: getattr(builtins, n) for n in %(names)s if hasattr(builtins, n)}
data = json.loads(sys.stdin.read())
tests = data["tests"]
ns = {}
try:
    exec(data["code"], {"__builtins__": safe}, ns)
except BaseException as e:
    print(json.dumps({"passed": 0, "total": len(tests),
                      "detail": "code did not load: %%s: %%s" %% (type(e).__name__, e)}))
    sys.exit(0)
fn = ns.get(data["entrypoint"])
if not callable(fn):
    print(json.dumps({"passed": 0, "total": len(tests),
                      "detail": "no callable named '%%s' was defined" %% data["entrypoint"]}))
    sys.exit(0)
passed = 0
first_fail = ""
for args, expected in tests:
    try:
        got = fn(*args)
    except BaseException as e:
        if not first_fail:
            first_fail = "%%r raised %%s: %%s" %% (args, type(e).__name__, e)
        continue
    if got == expected:
        passed += 1
    elif not first_fail:
        first_fail = "%%r returned %%r, expected %%r" %% (args, got, expected)
total = len(tests) or 1
detail = "all hidden tests passed" if passed == total else \
    "%%d/%%d passed; %%s" %% (passed, total, first_fail)
print(json.dumps({"passed": passed, "total": total, "detail": detail}))
""" % {"names": _SAFE_NAMES}


def _limits(cpu_s: int, memory_mb: int):  # pragma: no cover - runs in child
    def apply():
        if resource is None:
            return
        soft_cpu = max(1, cpu_s)
        resource.setrlimit(resource.RLIMIT_CPU, (soft_cpu, soft_cpu + 1))
        mem = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        except (ValueError, OSError):
            pass
    return apply


def run_code_sandboxed(
    code: str,
    entrypoint: str,
    hidden_tests: list,
    *,
    timeout_s: float = 3.0,
    memory_mb: int = 512,
) -> tuple[float, str, float]:
    """Run candidate ``code`` in an isolated subprocess; same return shape as run_code.

    ``hidden_tests`` are (args_tuple, expected) pairs; both must be JSON-serializable
    (use lists, not tuples, for expected return values). On timeout or crash the task
    scores 0.0 with an explanatory detail.
    """
    payload = json.dumps({
        "code": code,
        "entrypoint": entrypoint,
        "tests": [[list(args), expected] for args, expected in hidden_tests],
    })
    total = len(hidden_tests) or 1
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _DRIVER],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={"PATH": "/usr/bin:/bin"},
            preexec_fn=_limits(int(timeout_s) + 1, memory_mb) if resource else None,
        )
    except subprocess.TimeoutExpired:
        return 0.0, f"timed out after {timeout_s}s (possible infinite loop)", time.perf_counter() - t0
    latency = time.perf_counter() - t0

    if proc.returncode != 0 or not proc.stdout.strip():
        killed = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
        return 0.0, f"sandbox killed the process ({killed[0][:120]})", latency
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0.0, "sandbox produced unparseable output", latency
    return result["passed"] / total, result["detail"], latency
