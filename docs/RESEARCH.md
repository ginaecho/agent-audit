# Prior-art scan: how `agent-audit` is positioned

Before writing a line of the engine, we scouted the academic literature and the
open-source / commercial landscape (fan-out of Sonnet research agents, 2026-07).
This document records what already exists so the design stays honest about what
is genuinely new versus reused. **The short version: every individual stage of
`agent-audit` has a mature precedent; the novelty is composing them end-to-end
around a *per-requirement, auto-generated certification exam that gates team
formation*.** No system found does that full loop.

The pipeline and its nearest precedents:

```
requirement ─▶ STRATEGIST writes a bespoke audit ─▶ run vs. candidates ─▶ GRADE ─▶ HIRE ─▶ form TEAM
              (Self-Instruct, CodeT,            (AgentBench, GAIA,     (MT-Bench   (RouteLLM,  (AgentVerse,
               AutoBencher, CoEval)              WebArena as fixed      LLM-judge,  FrugalGPT,  DyLAN,
                                                 suites — not bespoke)  G-Eval,     NotDiamond) MetaGPT,
                                                                        Prometheus)             CaptainAgent)
```

## 1. An LLM *can* write the exam — but nobody uses it to hire

- **CodeT** (Chen et al., ICLR 2023, arXiv:2207.10397) — a model generates
  candidate solutions *and its own test cases*, then keeps the solution that
  passes. Near-literal precedent for "generate the test, then select by who
  passes." We borrow the "execution/checks as the objective signal" idea.
- **Self-Instruct** (Wang et al., ACL 2023, arXiv:2212.10560) — the canonical
  proof an LLM can bootstrap a broad, structured task set from a thin spec.
- **AutoBencher** (Li, Liang, Hashimoto et al., ICLR 2025, arXiv:2407.08351) —
  frames benchmark creation as optimization over *difficulty / salience /
  separating power*. Motivates our requirement that an audit must **discriminate**
  candidates, not rubber-stamp them.
- **BenchAgents** (Microsoft, arXiv:2410.22584) and **CoEval** (arXiv:2606.03650)
  — the closest analogs. CoEval synthesizes a fresh, contamination-free benchmark
  from *just a task description* and ranks candidate models with a cross-family
  judge ensemble (ρ≈0.86 vs. ground truth). **It stops at a ranking** — no
  pass/fail hiring gate, no team assembly. That final step is our contribution.
- **Task-specific RAG exam generation with Item Response Theory** (Guinet et al.,
  ICML 2024, arXiv:2405.13622) — auto-synthesizes a multiple-choice "exam" from a
  corpus and prunes uninformative questions via IRT to pick the best RAG config.
  The clearest "exam for candidate systems" precedent.
- **AdaRubric — task-adaptive rubrics** (Ding et al., 2026, arXiv:2603.21362) —
  generates an evaluation rubric on the fly from a task description and scores agent
  trajectories per-dimension, instead of applying a fixed rubric. This is the direct
  precedent for `agent-audit`'s strategist writing a bespoke `rubric` on every
  `llm_judge` check: the grading criteria are *derived from the requirement*, not
  templated. **CheckList**'s behavioral-test taxonomy (Minimum Functionality /
  Invariance / Directional tests) similarly informs the shape of the objective
  checks the strategist emits (`equals`/`contains`/`regex`/`json_path_equals`/…).

## 2. LLM-as-judge is mature — and so are its failure modes

We lean on this literature for the grader, and design against its documented
biases (see `agent_audit/grader.py`):

- **MT-Bench / Chatbot Arena** (Zheng et al., NeurIPS 2023, arXiv:2306.05685) —
  GPT-4 judges reach ~80%+ human agreement, but the paper catalogs **position,
  verbosity, and self-enhancement bias**.
- **G-Eval** (Liu et al., EMNLP 2023) and **Prometheus / Prometheus 2** (Kim et
  al.) — CoT + explicit user-supplied rubrics markedly improve judge/human
  correlation. Our grader always judges against a per-check rubric, never a bare
  "is this good?".
- **"LLMs are not Fair Evaluators"** (Wang et al., ACL 2024, arXiv:2305.17926) —
  response *order alone* flipped 66/80 verdicts. Motivates keeping objective
  deterministic checks first and reserving the judge for open-ended criteria.
- **Self-Preference Bias** (Wataoka et al., 2024, arXiv:2410.21819) and
  **"When LLMs Benchmark Themselves"** (arXiv:2509.26600) — a model that both
  *writes and grades* an exam favors models like itself. **This is why
  `agent-audit` separates the strategist (exam author) from the grader/judge**,
  and recommends a judge from a different model family than the candidates.

## 3. Routers select *models*, offline, on generic data — never a per-task audit

Every router screened chooses among **LLM API endpoints** (never heterogeneous
agents) using a **pre-trained classifier or price/latency metadata**, decoupled
from the user's actual task:

- **RouteLLM** (LMSYS, arXiv:2406.18665, Apache-2.0) — a binary strong/weak router
  trained offline on Chatbot Arena preferences; reads only the prompt, never
  grades the output. Repo last active ~Aug 2024.
- **FrugalGPT** (Chen, Zaharia, Zou, arXiv:2305.05176) — cascades with a DistilBERT
  reliability scorer trained on historical data; fixed escalation thresholds.
- **NotDiamond**, **Martian** — commercial per-request routers; custom routers are
  trained on *user-supplied* eval data, not generated from a spec.
- **OpenRouter**, **LiteLLM** (MIT) — gateway/load-balancers routing on
  price/uptime/latency; no output-quality grading at all.
- **Mixture-of-Agents** (Together AI, arXiv:2406.04692) — a fixed roster of
  proposers + an aggregator; every proposer always participates (no screening).

None runs a task-specific audit at hire time.

## 4. Orchestrators pick agents from a hand-curated roster — no admission test

All major frameworks do **dynamic-at-runtime selection from a fixed, developer-
defined set**; none gates membership on a generated capability test:

- **LangGraph** (MIT) — supervisor pattern routes via tool-calls among prebuilt nodes.
- **AutoGen** (MIT) — `SelectorGroupChat` picks the next speaker from a fixed roster.
- **CrewAI** (MIT) — static role/goal/backstory; optional hierarchical delegation.
- **OpenAI Agents SDK / Swarm** (MIT) — `handoffs` exposed as tools over a fixed set.
- **Semantic Kernel** (MIT) — `SelectionStrategy` / function-calling over registered agents.

Their eval tooling (LangSmith, Agents SDK evals, Braintrust, Inspect) is
**offline dev-time** evaluation or **runtime I/O guardrails** — not a
"test-then-hire" gate. The closest research is **AgentVerse** (ICLR 2024,
arXiv:2308.10848), whose "recruiter" agent dynamically composes a team, and
**DyLAN** (ACL 2024 Findings, arXiv:2310.02170), whose Agent Importance Score
selects a best subset — but both assign roles by prompting / live-task scoring,
without a pre-admission exam authored from the requirement.

## 5. Eval frameworks grade well, generate narrowly, and never hire

`promptfoo` (MIT, `generate dataset`/`generate assertions`), **DeepEval**
(Apache-2.0, `Synthesizer`), **RAGAS** (Apache-2.0, `TestsetGenerator`), and
**Giskard** (Apache-2.0, vuln scan) can synthesize tests — but from *documents,
prompts, or an existing model*, never from an abstract job description, and
always decoupled from candidate selection. **Inspect** (UK AISI, MIT) is a strong
scoring/agent-eval engine and a good candidate to plug in as the execution
backend later. Fixed benchmarks — **AgentBench, GAIA, SWE-bench, WebArena,
ToolBench, BFCL, HELM, Chatbot Arena, HF Open LLM Leaderboard** — are static
suites that *score*, never *hire*, and are not regenerated per requirement.

## 6. Governance tailwind

The audit trail this pipeline emits (versioned exam + rubric + transcripts +
decisions) is exactly what emerging governance asks for: **METR** pre-deployment
capability evals, **Singapore IMDA**'s Jan-2026 agentic-AI framework (verifiable
agent identity + who-acted-under-whose-authorization audit trail), the **EU AI
Act** GPAI transparency obligations, and **CSA**'s zero-trust-for-agents (favoring
*periodic re-certification*, which we model as re-runnable audits).

## Design decisions this scan forced

1. **Separate strategist from grader** — different roles, ideally different model
   families, to blunt self-preference bias (§2).
2. **Objective checks first, judge last** — deterministic checks
   (contains/regex/equals/JSON/numeric) carry the score where possible; the
   LLM-judge is reserved for open-ended criteria and always rubric-driven (§1, §2).
3. **Make the audit discriminative** — the strategist is prompted for varied
   difficulty and explicit competencies so the exam separates candidates (§1).
4. **Hire on a per-competency profile, then form a team** — not a scalar
   threshold; assign each competency-role to its best passer (DyLAN / MetaGPT
   flavor) (§3, §4).
5. **Everything is a logged, versioned artifact** — the exam, rubric,
   transcripts, and hiring rationale are first-class objects (§6).
6. **Flag untestable requirements** — the strategist must say when a requirement
   can't be reduced to a fair auto-gradable test rather than fabricate a
   low-fidelity exam (motivated by occupational-testability-gap findings).

_Verification note: the research proxy blocked direct fetches to arxiv.org and
several vendor domains, so a few arXiv IDs and vendor license details were
corroborated via search snippets rather than primary PDFs. Confirm specific IDs
before citing publicly._
