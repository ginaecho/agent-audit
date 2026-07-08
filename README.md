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

## How it fits together

| Module | Role |
|---|---|
| `strategist.py` | the powerful model that authors the audit from a requirement |
| `models.py` | dataclasses for the audit, results, and team (all JSON-serializable) |
| `providers.py` | `Provider` abstraction: `Anthropic`, `Mock` (offline), `Function` (agents) |
| `runner.py` | runs the audit against one candidate, aggregates per-competency scores |
| `grader.py` | deterministic checks + a separate rubric-driven LLM judge |
| `hiring.py` | pass/fail hiring and best-fit team formation |
| `pipeline.py` | wires it all together, emits the `AuditRun` artifact |

## Run the tests

```bash
pip install -e '.[dev]'
pytest
```

The suite runs the whole pipeline offline (deterministic mock providers) and unit-
tests every grader check.

## Status

Early prototype (v0.1). The engine is real and runnable; the offline path needs no
credentials. Natural next steps: pluggable execution backends (e.g. Inspect for
agentic/tool-use audits), adversarial/red-team test generation, multi-judge panels
with position-bias calibration, and periodic re-certification scheduling.

## License

MIT — see [`LICENSE`](LICENSE).
