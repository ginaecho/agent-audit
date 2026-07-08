# Audit-driven hiring of AI agents — design note

*Working draft / paper skeleton. Status: prototype + two free real-model validation
runs. Not yet a paid, controlled study.*

## Abstract

Selecting which model or agent to use for a task is, today, **decoupled from the
task**: routers train an offline classifier on generic preference data, orchestrators
pick from a hand-curated roster, and leaderboards rank on someone else's benchmark. We
propose **audit-driven hiring**: a strong "strategist" model reads a requirement, writes
a *bespoke, discriminating audit* (including executable tasks with hidden tests), runs
candidate LLMs/agents through it, and **hires** — assembling a team where each role is
staffed by the candidate that is *correct at the lowest cost* (fewest tokens / steps /
seconds). We report a working system and two free validation runs. The **cost** claim —
match top-tier quality at a fraction of the cost by certifying the cheapest sufficient
model per task — holds on both a text and an executable-code benchmark. The **quality-
routing** claim — reroute a role a weak model fails — remains untriggered because
frontier models pass our current tasks, and is the key next experiment.

## 1. Problem

Given a requirement `R` and a pool of candidate agents `C = {c_1..c_n}` (heterogeneous:
different base models, tools, skills), choose which candidate does each part of the
work, to maximize quality per unit cost. Existing approaches:

- **Routers** (RouteLLM, FrugalGPT, NotDiamond): per-query, offline-trained, prompt-only,
  models-not-agents, never grade the actual output against `R`.
- **Orchestrators** (LangGraph, AutoGen, CrewAI, …): dynamic selection from a *fixed,
  hand-defined* roster; no capability gate.
- **Auto-benchmarks** (AutoBencher, CoEval): an LLM authors a benchmark and *ranks*
  models — but stops at a ranking; no hiring, no team, no per-task tailoring to `R`.

Gap: nobody authors a **requirement-specific** audit and turns the result into a
**hiring + team-formation** decision over heterogeneous agents. (Full prior-art scan:
`RESEARCH.md`.)

## 2. Method

1. **Strategist authors an audit** from `R` — competencies + test cases + graders.
   Tests may be text checks *or* executable coding tasks with hidden tests
   (`strategist.design_coding_audit`).
2. **Discriminate by design** (`adaptive.py`): screen candidates, measure
   `discrimination_index`; if scores don't separate, harden the audit and retry. An
   audit everyone passes carries zero hiring signal.
3. **Score capability-per-cost** (`scoring.py`): a correct answer in fewer
   tokens / tool-calls / agent-steps / seconds beats a costlier one
   (`efficiency = correctness × cost_min/cost`). This is what separates equally-correct
   candidates.
4. **Executable/agentic tasks** (`execution.py`, `sandbox.py`): candidates solve by
   writing code that must pass hidden tests, run in an isolated subprocess sandbox;
   "shortest path to green" is the signal.
5. **Hire + form a team** (`hiring.py`): each competency-role goes to the best-fit
   (cheapest-correct) candidate; the top generalist leads; specialists are hired for the
   one role they win.
6. **Coach + re-audit** (`coach.py`): failures become an improvement plan whose skill
   text attaches to the agent; the same audit measures the uplift.

Author, grader, and candidates are three separate parties (self-preference bias).

## 3. Experiments & results

Two free validation runs using session models (opus/sonnet/haiku), graded offline by the
real code — deliberately *before* any paid API run.

- **Run 1 (text, claim verification).** All three models correct → correctness ties
  (discrimination 0.00). Efficiency scoring recovers the signal (0.81) and hires haiku.
- **Run 2 (executable code, held-out `insert`/`evaluate`).** All three correct on every
  hidden test. **audit-hire matched the best model's quality at ~1/5 the cost of
  always-opus** by certifying haiku suffices.

| (Run 2) strategy | quality | cost $ |
|---|---|---|
| audit_hire | 1.00 | 0.21 |
| always_haiku | 1.00 | 0.21 |
| always_sonnet | 1.00 | 0.81 |
| always_opus | 1.00 | 1.08 |

Details + tables: `RESULTS.md`.

## 4. Findings

- **The cost win is real and reproduced.** A requirement-specific audit lets you hire the
  cheapest *sufficient* candidate and match top-tier quality far cheaper — the FrugalGPT
  result, but per-task-audit-driven and extended to executable/agentic tasks.
- **Correctness-only scoring is a trap.** On common tasks, frontier models tie; the
  hiring signal lives in *capability-per-cost*, not pass/fail.
- **The audit is a certificate, not a gamble.** audit-hire ties always-cheapest when the
  cheap model happens to suffice — but it *knows* it suffices (screened), whereas
  always-cheapest fails silently the first time it doesn't.

## 5. Limitations / threats to validity

- **Quality-routing unproven.** Our tasks don't make frontier models fail, so the
  reroute-on-failure case never fired. Needs discriminating tasks or a genuinely weak
  candidate.
- **Free runs are directional.** Session models ≈ opus-4-8/sonnet-5/haiku-4-5, not the
  full 4-model policy; single-shot, not multi-step agent loops; token counts include
  subagent overhead; subagent latency is noisy (excluded from headline).
- **Sandbox is defense-in-depth, not a jail.** rlimits + restricted builtins, not full
  network/fs isolation (see `sandbox.py`).
- **Author ≈ candidate overlap** in the free runs (opus stood in as strategist and
  candidate); the paid run separates them.

## 6. Next experiments

1. **Trigger quality-routing.** Add a genuinely weak candidate and/or adversarial tasks
   until a competency separates on *correctness*; show audit-hire beats always-cheapest on
   quality and always-opus on cost — the headline result.
2. **Multi-step agentic loops on real models** (write→run→fix), so path-length and speed
   discriminate, not just token price.
3. **Paid, controlled run** of the faithful 4-model policy with separated
   strategist/judge/candidates (`experiments/run_harness.py`).
4. **Coaching uplift**, measured on held-out tasks (not just the coached audit).

## Reproduce

```bash
pip install -e '.[dev]' && pytest                     # 40 offline tests
python experiments/run_authored_agentic_audit.py      # auto-designed + sandboxed pipeline
python experiments/subagent_run_agentic.py            # the run-2 numbers above
```
