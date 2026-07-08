# agent-audit

**Audit-driven screening to hire and team up AI agents.**

A strategist LLM (the most capable model in the system) reads your requirement,
**writes a bespoke audit** — an exam, with competencies, test cases, and grading
checks — then runs that audit against candidate LLMs and agents. The ones that pass
are **hired**, and the passers are **assembled into a team**, each role staffed by
the candidate that scored best on it. The whole run is captured as a single
auditable, versioned JSON artifact.

The test *is* the deliverable: the strongest agent designs it, and it decides who
gets the job.

```
  requirement ──▶  STRATEGIST  ──▶   AUDIT   ──▶  screen every  ──▶  GRADE   ──▶  HIRE  ──▶  TEAM
 (user intent)   (Opus 4.8 writes   (competencies,   candidate      (objective    (per-      (best-fit
                  the exam)          test cases,      on the exam     checks +     competency  hire per
                                     checks)                          rubric judge) profile)   role, + lead)
```

## Why this doesn't already exist

We scouted the literature and the tooling landscape before building (full writeup:
[`docs/RESEARCH.md`](docs/RESEARCH.md)). Every individual stage has a mature
precedent — but **no system chains them into "write a bespoke exam per requirement,
screen candidates on it, and hire a team from the passers"**:

| Existing tools | What they do | What they don't |
|---|---|---|
| **Eval frameworks** — promptfoo, DeepEval, RAGAS, Inspect, Braintrust | grade outputs; some generate tests *from documents* | never generate an exam from an abstract requirement; never *hire* |
| **Model routers** — RouteLLM, FrugalGPT, NotDiamond, OpenRouter, LiteLLM | route each query to a model via an offline classifier or price/latency | never grade the actual output against a task-specific audit; models only, not agents |
| **Orchestrators** — LangGraph, AutoGen, CrewAI, OpenAI Agents SDK, Semantic Kernel | pick an agent at runtime from a **hand-curated roster** | no capability audit gates who's on the team |
| **Auto-benchmarks** — AutoBencher, BenchAgents, CoEval | an LLM authors a benchmark and ranks models | stop at a *ranking* — no pass/fail hiring, no team |

The novelty is the **composition**, and specifically the last step everyone stops
short of: turning audit results into an actual hiring-and-teaming decision.

## Design choices the research forced

- **Strategist ≠ grader.** A model that writes *and* grades its own exam favors
  models like itself (self-preference bias). The exam author and the judge are
  separate roles, ideally different model families.
- **Objective checks first, judge last.** Deterministic checks
  (`contains`/`regex`/`equals`/`json_path_equals`/`numeric_close`/…) carry the score
  wherever possible; the LLM judge is reserved for open-ended criteria and is always
  driven by an explicit rubric.
- **Hire on a per-competency profile,** not a single scalar — so a specialist can
  win its role even if it isn't the top generalist.
- **Every run is an artifact.** The exam, transcripts, and hiring rationale
  serialize to JSON — the audit trail emerging governance (METR, Singapore IMDA, EU
  AI Act) is asking for. Re-run the same audit later to re-certify.

## Install

```bash
pip install -e .                    # core engine, zero dependencies, runs offline
pip install -e '.[anthropic]'       # + screen real Claude models
```

## Quickstart — offline, no API key

```bash
agent-audit --demo
```

```python
from agent_audit.demo import build_demo

pipeline, requirement, candidates = build_demo()
run = pipeline.run(requirement, candidates)
print(run.summary())
```

The demo screens three candidates (a strong generalist, a weak bot, and a
JSON-specialist) for a billing-desk assistant and shows the generalist hired as
lead while the specialist still wins the `json_lookup` role.

## Screen real Claude models

```bash
export ANTHROPIC_API_KEY=sk-ant-...
agent-audit "Answer billing questions accurately, return JSON for order lookups, \
and never give legal advice" \
  --candidates claude-haiku-4-5 claude-sonnet-5 claude-opus-4-8 \
  --out runs/billing.audit.json
```

```python
from agent_audit import AuditPipeline, AnthropicProvider

pipeline = AuditPipeline(
    strategist=AnthropicProvider("claude-opus-4-8", effort="high", max_tokens=8000),
    judge=AnthropicProvider("claude-sonnet-5", name="judge"),
)
candidates = [AnthropicProvider(m) for m in
              ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8")]
run = pipeline.run(requirement, candidates)
print(run.summary())
```

**Candidates can be agents, not just models.** Wrap any `(prompt, system) -> str`
callable — one that runs tools, memory, and scaffolding — in a `FunctionProvider`
and screen it on equal footing with raw models.

```python
from agent_audit import FunctionProvider

my_agent = FunctionProvider("rag-agent", lambda prompt, system: my_rag.run(prompt))
run = pipeline.run(requirement, [my_agent, AnthropicProvider("claude-sonnet-5")])
```

## The evaluation harness: does audit-hiring actually beat naive picks?

The falsifiable claim this project rests on: **an LLM-authored, requirement-specific
audit predicts on-the-job performance better than picking by leaderboard rank or by
"just use the biggest model."** `agent_audit/harness.py` + `experiments/` run that
experiment end to end:

1. the strategist authors an audit from the requirement (never sees the job tasks);
2. candidates are screened and a team is hired;
3. every strategy then answers **held-out job tasks** the audit never saw —
   `audit_hire` routes each task to the team member staffed on its competency,
   while each baseline uses one fixed model for everything;
4. the same judge grades all job answers, and provider token usage is priced, so
   the output is a **quality + cost** table per requirement.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python experiments/run_harness.py          # all three requirement cases
```

**Model policy for the study (no Fable 5 anywhere):**

| Role | Model | Why |
|---|---|---|
| strategist (authors exam) | `claude-opus-4-8` | most capable; **not** a candidate |
| judge (grades rubrics) | `claude-opus-4-7` | strong; **not** a candidate, **not** the author |
| candidates under audit | `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-haiku-4-5` | the pool being hired from |
| baselines | biggest (`opus-4-6`) · leaderboard pick (`sonnet-5`) · cheapest (`haiku-4-5`) | what audit-hire must beat |

Author, grader, and examinees are three separate parties by construction
(self-preference bias, see `docs/RESEARCH.md` §2).

## The audit is also a coach: audit → guidance → improve → re-audit

An agent is a model **plus skills** — so improving an agent's skills is itself a
hiring path, and the audit should both *guide* and *verify* that improvement.
`agent_audit/coach.py` turns a candidate's concrete failures (which check, what was
expected, what it answered) into an `ImprovementPlan` whose `skill_text` attaches
straight onto the agent:

```python
from agent_audit import Coach, SkilledProvider

plan   = Coach(coach=strategist).improvement_plan(audit, report_a)   # diagnose A
agent_b = SkilledProvider(agent_a, plan.skill_text)                  # A + skill = B
run_b  = pipeline.run(requirement, [agent_b], audit=audit)           # SAME exam
```

The re-run uses the *same* audit, so the uplift is measured by the instrument that
prescribed it. Guidance is generalized ("always return ONLY a JSON object with the
requested keys"), never the literal test answers. Try it on the weakest model:

```bash
python experiments/run_coaching.py --candidate claude-haiku-4-5
```

## The strategist's real skill: design until it discriminates, score capability-per-cost

An audit where every candidate scores the same is worthless for hiring. So the
strategist (the most powerful agent) does two things beyond writing questions:

**1. Efficiency-weighted scoring (`scoring.py`).** Correctness alone often ties
capable models. The real signal is **the shortest / cheapest path to a correct
answer** — a correct answer in fewer tokens, fewer tool-calls, fewer agent-loop
steps, and less wall-clock time (speed) beats one that cost more. `discrimination_index`
tells you whether a set of scores actually separates candidates. Re-scoring the real
run-1 data (see `docs/RESULTS.md`): correctness discrimination `0.00` → efficiency
discrimination `0.81`, hiring `haiku` (correct **and** cheapest).

**2. Adaptive discrimination loop (`adaptive.py`).** The strategist authors an exam,
screens the candidates, measures separation, and if they're too close it **hardens
the exam and retries** until they're distinguishable (AutoBencher-style separability,
run online per requirement).

**3. Executable / agentic tasks (`execution.py`).** The sharpest discrimination comes
from tasks the candidate must *solve*, not answer: "write a function that passes these
hidden tests" (or "use this MCP tool to retrieve X"). Candidates run in an agent loop
— write → run → read the error → fix — and the score is **who reaches green in the
fewest steps / tokens / seconds**. `Effort(tokens, tool_calls, steps, latency_s)` and
`AGENTIC_WEIGHTS` fold speed and path length into the ranking.

**The strategist authors these tasks itself** (`Strategist.design_coding_audit`) —
LLM-generated prompts *and hidden tests*, with the same `harden_feedback` hook so the
adaptive loop drives auto-designed coding audits. And candidate code runs in a
**subprocess sandbox** (`sandbox.run_code_sandboxed`): CPU/memory/file rlimits, a
wall-clock timeout, a scrubbed env, and restricted builtins (no `open`, no imports) —
a drop-in `runner=` for `solve_coding_task`. (Defense in depth, not a guarantee; for
hostile code at scale, wrap it in a container with no network.)

The pieces compose — the loop uses the executable tasks' sharp signal to know when
the exam separates. See it end to end (offline, no key):

```bash
python experiments/run_agentic_audit.py             # adaptive design + executable scoring
python experiments/run_authored_agentic_audit.py    # strategist authors tasks + sandboxed run
```

```
round 0: discrimination 0.00 ✗ too close  [ace:1.00  grinder:1.00  novice:1.00]
round 1: discrimination 1.00 ✅ separates  [ace:1.00  grinder:0.49  novice:0.00]
=> hire: ace  (reaches green correctly in the fewest steps/tokens/time)
```

## How it fits together

| Module | Role |
|---|---|
| `strategist.py` | the powerful model that authors the audit from a requirement |
| `models.py` | dataclasses for the audit, results, and team (all JSON-serializable) |
| `providers.py` | `Provider` abstraction: `Anthropic` (usage/cost-tracked), `Mock` (offline), `Function` (agents), `Skilled` (agent = model + skill) |
| `runner.py` | runs the audit against one candidate, aggregates per-competency scores |
| `grader.py` | deterministic checks + a separate rubric-driven LLM judge |
| `hiring.py` | pass/fail hiring and best-fit team formation (specialist hires included) |
| `coach.py` | failures → improvement plan → attachable skill (the coaching loop) |
| `scoring.py` | efficiency scoring (cheapest/shortest-path-to-correct) + discrimination metrics |
| `adaptive.py` | the loop that hardens the exam until candidates separate |
| `execution.py` | executable/agentic tasks (strategist-authored) scored by shortest-path-to-green |
| `sandbox.py` | subprocess sandbox (rlimits + timeout + restricted builtins) for untrusted code |
| `harness.py` | audit-hire vs. baselines on held-out job tasks, quality + cost |
| `pipeline.py` | wires it all together, emits the `AuditRun` artifact |
| `experiments/` | requirement cases + real-model runners for the study above |

## Run the tests

```bash
pip install -e '.[dev]'
pytest
```

The suite runs the whole pipeline offline (deterministic mock providers) and unit-
tests every grader check.

## Conclusion — a discriminating audit is expensive and low-yield to build

The experiments carry a sobering cost lesson: **generating a batch of *correct,
discriminating* tests is neither easy nor cheap.** Frontier tiers are saturated on
clean, single-answer tasks, so most well-formed tests come back a **tie** and carry
zero hiring signal. Finding one honest quality gap took a long search:

- **~24 candidate interviews this session** (opus/sonnet/haiku across 5 test
  designs), on top of ~8 prior hard coding problems that all tied.
- **Yield: ~1 discriminating design out of ~3 tried** — and the one that worked
  (`experiments/results/reliability_sweep.md`) only revealed the gap by running each
  item **4× per model** to measure reliability, not correctness.
- Every test also needs **objective ground truth** (here, brute-force reference
  solutions and hidden-test suites), which the strategist must author and verify —
  the real bottleneck, and itself Opus-priced work.

**Cost of the candidate runs** (these were *free* via session models; priced as if
billed by API — `python experiments/cost_estimate.py`):

| model | tokens | cost (output-rate upper bound) |
|---|---|---|
| opus | 174,193 | $4.35 |
| sonnet | 217,556 | $3.26 |
| haiku | 165,381 | $0.83 |
| **total** | **557,130** | **~$8.45** (realistically ~$3–5, much is cached context) |

That ~$8 buys *only the candidate interviews* for one session. The costlier,
serial part is the **strategist (Opus 4.8) rounds that generate the tests** — design
a test, author brute-force ground truth, grade, iterate — once per round, and most
rounds tie. Counting those rounds (estimate; the main loop's own tokens aren't
exposed to it, so per-round tokens are modeled — see `experiments/cost_estimate.py`):

| | rounds | Opus 4.8 cost (est.) |
|---|---|---|
| this session | 4 | ~$2.2 |
| whole project | **~16** | **~$5** |
| — of which tied (no signal) | 15 / 16 | ~$3.5 wasted |

At ~$0.23/round (4k output @ $25/Mtok + 18k fresh input @ $5 + 90k cached context
@ ~$0.50), **finding one genuine quality gap cost ~16 Opus 4.8 rounds ≈ $5.** In this
streamlined session that lands *comparable* to the candidate interviews rather than
far above them — but it is a **floor**, because here ground truth was hand-authored
in Python rather than driven through Opus's full adaptive-hardening loop. At scale the
strategist becomes the dominant line item for three compounding reasons: (1) it runs at
the highest per-token price (Opus 4.8, 5× haiku output), (2) Opus 4.8 *also* serves as
the verbal-task **judge**, touching most of the pipeline, and (3) low discrimination
yield means **many rounds** — you pay Opus repeatedly to author tests that mostly tie.
Scaled to the full 4-model policy with paid API calls, adaptive design loops, and
repeated sampling, a single discriminating audit is a
**multi-dollar-to-tens-of-dollars** exercise, most of it Opus-priced design spend on
tests that don't separate anyone.

**Implication for the design:** an audit is a *certificate you pay for*, so spend
must be justified by decisions it changes. Practical levers: reuse/cache
discriminating items across requirements; screen cheap models first and only
escalate sampling where scores are close; prefer **stochastic, simulator-graded
tasks** (§`docs/FINDINGS_AND_OPEN_PROBLEMS.md`) that discriminate on the first run
over closed-form problems that tie; and budget the number of repeated trials against
the discrimination they actually buy. Cheap-to-run correctness checks are a trap —
the signal lives in capability-per-cost and reliability, which cost more to measure.

## An alternative to authoring tests: rank agents from real usage

If auto-generating tests is this expensive and hits a ceiling (a model can't author
items past its own blind spots — see `docs/FINDINGS_AND_OPEN_PROBLEMS.md`), the other
road is to **stop authoring tests and harvest ground truth that already exists**: the
outcomes of real agent sessions. [`agent_audit/tracerank`](agent_audit/tracerank) parses
VS Code/Copilot chats and Claude Code sessions into a difficulty-adjusted capability
leaderboard, weighted toward hard evidence (tests passed/failed, builds, votes) over
soft sentiment, and turns each agent's recurring failures into concrete improvement
skills. See [`docs/TRACERANK.md`](docs/TRACERANK.md) — including an honest finding from
validating it against this project's own traces: it only works when the trace *itself*
contains outcome evidence; single-shot Q&A graded elsewhere leaves nothing to find.

```bash
python -m agent_audit.tracerank --demo
python -m agent_audit.tracerank --source claude-code --demo
```

## Status

Early prototype (v0.1). The engine, coaching loop, and evaluation harness are real
and runnable; the offline path needs no credentials, and `experiments/` is ready to
run against real models once results are wanted. Natural next steps: run the study
and report the quality/cost table, pluggable execution backends (e.g. Inspect for
agentic/tool-use audits), adversarial/red-team test generation, multi-judge panels
with position-bias calibration, and periodic re-certification scheduling.

## License

MIT — see [`LICENSE`](LICENSE).
