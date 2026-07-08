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

### Evaluation is routed by task type

- **Coding / system tasks (verifiable) → deterministic numeric scoring.** Hidden tests
  → pass rate, plus cost / steps / speed. No LLM in the grading loop; fully reproducible
  (`execution.py`, `sandbox.py`, `scoring.py`). The strategist's job here is to author
  the *goals and numeric criteria* (the hidden tests and thresholds).
- **Verbal / free-text tasks (subjective) → LLM-as-judge by the most capable model**
  (Opus 4.8), against the explicit rubric the strategist wrote (`grader.py`). Judging
  open-ended quality is the hardest, least-verifiable step, so it gets the strongest
  model — kept out of the candidate pool (or run as a cross-family panel) to avoid
  self-preference.

The strategist authors both halves; the *grader* never guesses — it either runs code
against numeric criteria, or scores text against a rubric.

## 3. Experiments & results

Three free validation runs using session models, graded offline by the real code —
deliberately *before* any paid API run.

- **Run 1 (text, claim verification).** All three models correct → correctness ties
  (discrimination 0.00). Efficiency scoring recovers the signal (0.81) and hires haiku.
- **Run 2 (executable code).** All three correct on every hidden test. **audit-hire
  matched the best model's quality at ~1/5 the cost of always-opus** by certifying haiku
  suffices.
- **Run 3 (executable code, weak cheap agent added).** A deliberately weak-but-cheapest
  agent `nano` is broken on `intervals` (its `merge` returns tuples), fine on `parsing`.
  The audit hires a **mixed team** (haiku for intervals, nano for parsing):

| (Run 3) strategy | quality | cost $ |
|---|---|---|
| **audit_hire** | **1.00** | **0.12** |
| always_haiku | 1.00 | 0.21 |
| always_opus | 1.00 | 1.08 |
| always_nano (cheapest) | 0.50 | 0.04 |

audit-hire is the only strategy at perfect quality *and* lowest cost: it **beats
always-cheapest on quality** (1.00 vs 0.50 — the quality-routing win) and **always-
biggest on cost** (9×). Details + tables: `RESULTS.md`.

## 4. Findings

- **The cost win is real and reproduced** (runs 1-2). A requirement-specific audit lets
  you hire the cheapest *sufficient* candidate and match top-tier quality far cheaper —
  the FrugalGPT result, but per-task-audit-driven and extended to executable/agentic tasks.
- **The quality win fires when the pool is heterogeneous** (run 3). With a cheap-but-weak
  agent present, audit-hire forms a mixed team — exploiting the cheap agent where it works,
  routing around it where it fails — and is the only strategy that reaches perfect quality
  at the lowest cost, beating always-cheapest on quality and always-biggest on cost.
- **Correctness-only scoring is a trap.** On common tasks, frontier models tie; the
  hiring signal lives in *capability-per-cost*, not pass/fail.
- **The audit is a certificate, not a gamble.** Always-cheapest fails silently the first
  time the cheap agent can't do the job; audit-hire has screened it and knows.

## 5. Limitations / threats to validity

- **Quality-routing shown with a constructed weak agent.** Run 3's `nano` is a real model
  given a terse persona; its failure is a type bug, not a deep capability gap. The
  *mechanism* is demonstrated, but a stronger result would use genuinely distinct tiers or
  naturally-occurring capability gaps rather than an induced one.
- **Free runs are directional.** Session models ≈ opus-4-8/sonnet-5/haiku-4-5, not the
  full 4-model policy; single-shot, not multi-step agent loops; token counts include
  subagent overhead; subagent latency is noisy (excluded from headline).
- **Sandbox is defense-in-depth, not a jail.** rlimits + restricted builtins, not full
  network/fs isolation (see `sandbox.py`).
- **Author ≈ candidate overlap** in the free runs (opus stood in as strategist and
  candidate); the paid run separates them.

## 6. Next experiments

1. ✅ **Trigger quality-routing** — done (run 3), with an induced weak agent. Next:
   reproduce it with *naturally* distinct tiers / genuine capability gaps, not a persona.
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
