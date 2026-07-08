# Findings, hard problems, and an application proposal

*A gathering of what the audit experiments have shown, where agents actually do
poorly (and why those tasks are hard to audit), and a concrete proposal for a
real application — the low-utilization scheduling problem — including how to
audit an agent on it.*

---

## 1. What we now know (from the audit experiments)

### 1.1 The system, briefly
A strong "strategist" (Opus 4.8) reads a requirement, authors a *discriminating*
audit (verifiable coding tasks with hidden tests, or verbal tasks with a rubric),
screens candidate models/agents, and **hires** a team where each role goes to the
candidate that is *correct at the lowest cost*. Evaluation is routed by task type:
verifiable coding/system tasks → deterministic numeric scoring (sandbox, hidden
tests); verbal/free-text → LLM-as-judge by the most capable model against the
strategist's rubric. (Pipeline: `agent_audit/`, prior runs: `RESULTS.md`.)

### 1.2 The two claims and their honest status
- **Cost win — REAL, reproduced (runs 1–2).** A requirement-specific audit lets
  you hire the cheapest *sufficient* candidate and match top-tier quality at a
  fraction of the cost (FrugalGPT-style, but per-task-audit-driven and extended to
  executable tasks). Certifying that haiku suffices matched always-opus quality at
  ~1/5 the cost.
- **Quality-routing — REAL, but only under the right lens.** It fires when the
  pool actually contains a weaker candidate on some competency. First shown with an
  *induced* weak agent (run 3). Now shown with a **genuine, unmodified** gap
  (run 5, below) — but only after switching the measurement from single-shot
  correctness to **reliability under repeated sampling**.

### 1.3 The central lesson: correctness ties, reliability separates
On clean, well-specified, single-answer tasks, **frontier tiers do not separate on
correctness.** We verified this hard:

- **8 hard coding problems** (calculate, regex/wildcard, valid-paren, int-to-words,
  multiply, rectangle-union differential-tested against a brute-force reference,
  …): opus / sonnet / haiku all **tied at 1.00**.
- **A 10-item prose reasoning battery** (hard digit-sum counting, derangements,
  knights-and-knaves, expected-value, work-rate, age algebra), screening + held-out,
  graded against brute-forced ground truth: opus 10/10, sonnet 10/10, haiku 10/10 —
  a **clean tie**. (A single earlier haiku miss did **not** reproduce; treating that
  one sample as a "gap" would have been cherry-picking — i.e., cheating.)

The signal only appears when you **sample repeatedly and measure the pass rate**
(run 5): the same hard counting battery, 4 trials per model, graded against
ground truth —

| model  | item pass-rate | trials fully correct |
|--------|----------------|----------------------|
| opus   | 20/20 = **1.00** | 4/4 |
| sonnet | 20/20 = **1.00** | 4/4 |
| haiku  | 13/20 = **0.65** | 1/4 |

Haiku is reliable on small/few-term instances but slips on the harder ones
(6-digit ranges needing more inclusion–exclusion terms): it drops terms, makes
arithmetic errors, and picks an error-prone decomposition that compounds mistakes.
Opus/sonnet use the closed form and self-check → 100%. **This is the genuine,
non-cheating quality differentiator among frontier tiers:** identical fair prompts,
objective ground truth, unmodified models, no persona, no tooling artifact —
detected by reliability, not a single sample. (Details: `experiments/results/reliability_sweep.md`.)

**Design consequences for the audit:**
1. *Correctness-only scoring is a trap.* On common tasks it flatlines at 1.00.
   Hire on **capability-per-cost** and **reliability**, not pass/fail.
2. *Budget repeated trials.* A discriminating audit for frontier tiers must sample
   each hard item several times and score the pass rate; one shot hides the gap.
3. *Route on the reliability gap.* For the counting competency, audit-hire routes
   to the cheapest **reliable** passer (sonnet, 100%, cheaper than opus), rejects
   haiku (65%) there, and still uses cheap haiku on competencies where it's reliable
   — beating always-haiku on quality and always-opus on cost.

---

## 2. Where agents do poorly (a taxonomy of hard-to-audit tasks)

Three classes, in increasing order of how hard they are to *grade* faithfully.

### 2.1 Verifiable but reliability-sensitive (multi-step arithmetic / counting)
**Symptom:** correct in expectation, wrong on a fraction of runs — dropped a term,
a transcription slip, an off-by-one in a long inclusion–exclusion. Exactly the
run-5 finding.
**Why it's easy to *grade* but easy to *mis-audit*:** ground truth is objective
(brute force), but a single sample reports a tie. The failure is **variance**, not
a deterministic wrong answer.
**How to audit well:** sample K times per item, score the pass rate; report
discrimination on reliability. Optionally require the model to self-check
(symmetry, a second method) and measure whether it catches its own slip.

### 2.2 Internet scouting & citation (fabricated links, weak abstraction)
This is the user's example (1), and it is where agents are **most confidently wrong.**
**Failure modes we should expect and test for:**
- **Hallucinated / malformed URLs** — plausible-looking links that 404 or never
  existed; invented DOIs / arXiv IDs.
- **Citation–claim mismatch** — the link resolves, but the page does not actually
  support the sentence it's attached to (the model abstracted a detail that isn't there).
- **Stale facts** past the knowledge cutoff, stated with full confidence.
- **Over-compression** — a summary that drops the qualifier that made the source true
  ("effective in trial X" → "effective", losing the population/endpoint).
- **Source laundering** — citing a blog that cited a paper, as if the primary source.

**Why it is hard to audit:** the ground truth lives *outside the model* and changes
over time. An LLM-as-judge **cannot** confirm that a URL resolves or that a page
supports a claim — it will often rubber-stamp a fabricated-but-plausible citation.
Self-report is worthless here.

**How to audit it properly — tool-grounded grading (not pure LLM judge):**
1. Require structured output: a list of `{claim, url, quoted_span}` triples, not prose.
2. The grader **fetches every URL**: check it resolves (HTTP 200, not a soft-404),
   and that `quoted_span` actually appears on the page (string/fuzzy match).
3. **Support check:** does the fetched text entail the `claim`? This is the one step
   that may use the strong judge — but *anchored to the fetched text*, not the
   model's memory, which removes most of the self-preference/hallucination risk.
4. Score = fraction of claims that are **link-valid AND support-valid**, with a
   heavy per-fabricated-link penalty (a made-up citation is worse than a missing one).
   This is a *verifiable* task (mostly deterministic), not a subjective one — it
   routes to the numeric side of the framework, with the judge used only for
   entailment against real text.

**Caveat for this offline harness:** the free session subagents don't have reliable
live web access, so we can *design* this audit but not *run* it here; it needs a
tool-enabled candidate and a fetching grader.

### 2.3 Open-ended operations / optimization proposals
The user's example (2). "Correct" is not a single value; a good answer is a
*quantitative model + policy* evaluated against stochastic objectives. Agents do
poorly when they hand-wave: generic advice, ignoring stochasticity, arithmetic
errors in the utilization computation, or a policy that looks reasonable but
simulates badly. This class is the bridge to §3 — and, unlike closed-form
algorithmics, it is exactly the kind of task that **should** produce a genuine
quality spread, because the objective is stochastic and open-ended.

---

## 3. Application proposal — the low-utilization scheduling problem

*Setting: resources (imaging machines / exam rooms / clinicians) whose utilization
is low despite "full-looking" schedules, because exam durations differ, scheduling
gaps fragment the day, and patients change over time (no-shows, cancellations,
case-mix drift).*

### 3.1 Why utilization is low (diagnose before optimizing)
Utilization = productive busy time ÷ available capacity. The losses:
- **(a) Duration heterogeneity vs fixed slot granularity** — a 20-min gap stranded
  between two 45-min exams booked on 30-min templates. The single biggest, most
  fixable loss.
- **(b) Buffer / turnover over-allocation** — the same clean-down/setup buffer applied
  to a 10-min and a 90-min exam.
- **(c) No-shows & late cancellations** — holes that open too late to backfill.
- **(d) Case-mix / demand drift** — templates tuned to last quarter's mix mismatch
  this quarter's (patients change over time).
- **(e) Sequencing effects** — a long case wedged where only short cases fit,
  fragmenting the tail of the day.

### 3.2 Levers (the actual proposal)
1. **Case-mix-aware, variable-length templates.** Bin slot lengths to the *duration
   distribution per exam type*, not one fixed grid. Re-fit as mix drifts.
2. **Predictive duration model** per (exam type, modality, patient factors). Schedule
   to a chosen quantile (e.g., P60) + a small shared buffer, not worst case — worst-case
   buffering is a top cause of idle.
3. **Calibrated overbooking** where no-show probability is high, bounded by an
   overtime/wait-risk constraint (airline-style, but per-slot and risk-capped).
4. **Dynamic backfill.** A short-notice fill queue + waitlist; rolling-horizon
   re-optimization triggered by each cancellation. This is what recovers loss (c).
5. **Sequencing / bin-packing** to minimize idle fragmentation: place long cases
   first, pack short cases into residual gaps; avoid leaving unfillable slivers.
6. **Right-size buffers/turnover by modality** instead of a flat buffer.

### 3.3 Make it auditable — formulate, don't hand-wave
- **Objective:** maximize E[utilization] (equivalently minimize idle + overtime +
  expected wait), **subject to** overtime ≤ budget and P(patient wait > τ) ≤ α.
- **Stochastic model:** durations ~ per-type distribution; no-show ~ Bernoulli(p_slot);
  arrivals/cancellations ~ a process over the booking horizon.
- **Methods:** stochastic MIP for template design; **discrete-event simulation /
  simulation-optimization** to evaluate a policy; rolling-horizon MPC (or an RL
  policy) for the dynamic backfill; sensitivity analysis over p and the mix.
- **KPIs:** utilization %, idle minutes, overtime minutes, mean & P95 patient wait,
  throughput, fraction of no-show holes backfilled.

### 3.4 How the AUDIT framework selects and coaches an agent for this
This is where §1–§3 join, and why this application is a *better* discriminator than
closed-form algorithmics:

- **Build the audit as a discrete-event simulator that IS the deterministic grader**
  (coding/system task → numeric; no LLM judge). Hand the candidate a synthetic
  clinic instance (duration distributions, no-show rates, arrival/cancel process,
  capacity). The candidate must output a **scheduling policy** — as code or
  parameters (template, per-slot overbook vector, backfill rule).
- The **hidden simulator** runs the policy over many sampled days and returns
  utilization / overtime / wait. **Score** = achieved objective vs a reference
  optimizer, with hard penalties for constraint violations. Fully reproducible.
- **Why it discriminates (unlike clean algorithmics):** the objective is stochastic
  and open-ended, many policies are valid, and quality varies *continuously* — so
  models separate. "Shortest / cheapest reliable path" still applies: a strong agent
  reaches high utilization in fewer iterations and tokens.
- **Coaching loop:** the audit's failure report ("your template strands 18% idle on
  long-exam days"; "your overbooking blew the overtime cap at the α you chose")
  becomes an `ImprovementPlan.skill_text` (see `coach.py`), attached to the agent;
  the same simulator re-audits and measures the uplift — the audit → guidance →
  skill → re-audit loop, on a real objective.
- **Web-scouting as a separate role.** Gathering guideline exam durations, published
  no-show rates, and modality benchmarks is a *distinct* competency — audit it with
  the §2.2 tool-grounded citation grader and hire whichever candidate is
  link-reliable. Don't let a strong optimizer that fabricates citations staff the
  research role.

---

## 4. Open questions / what is still hard

- **Frontier tiers are saturated on clean single-answer tasks.** A genuine quality
  spread required moving to (a) repeated-sampling *reliability*, or (b) *stochastic,
  open-ended objectives* (the scheduling sim). Expect ties anywhere the answer is a
  single verifiable value.
- **Web-scouting can't be audited offline.** It needs tool-enabled candidates and a
  fetching grader; the free session path can design but not run it.
- **A simulation-graded audit is only as good as the simulator's fidelity** to the
  real clinic (duration tails, correlated no-shows, add-on/emergency cases). Garbage
  sim → confidently-wrong hire.
- **Reliability costs trials.** Sampling K times to measure the pass rate multiplies
  audit cost; the strategist must budget trials against the discrimination it buys.
- **Self-preference on the entailment step.** Using the strong model to judge
  citation support is safe only because it's anchored to fetched text; unanchored, it
  reintroduces the bias the framework is built to avoid.
