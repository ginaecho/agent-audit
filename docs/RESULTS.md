# Results

## Run 5 — a GENUINE quality gap, found honestly via reliability, 2026-07

Runs so far showed frontier tiers tie on *single-shot correctness* — 8 hard coding
problems and a 10-item prose reasoning battery all tied at 1.00 (opus = sonnet =
haiku). A single early haiku miss on one counting item did **not** reproduce when
re-run in a controlled battery (all three hit 10/10); reporting that lone sample as
a "gap" would have been cherry-picking, i.e. cheating, so we didn't.

The honest differentiator appears only under **repeated sampling**. The same hard
inclusion–exclusion counting battery (5 items: digit-sum counts over large ranges),
run **4 times per model**, prose-only (no code, no tools), graded against
brute-forced ground truth:

| model  | item pass-rate | trials fully correct |
|--------|----------------|----------------------|
| opus   | 20/20 = **1.00** | 4/4 |
| sonnet | 20/20 = **1.00** | 4/4 |
| haiku  | 13/20 = **0.65** | 1/4 |

Haiku is reliable on small/few-term items (P1 4/4, P4 4/4) but slips on the 6-digit
ranges needing more inclusion–exclusion terms (P2 2/4, P3 2/4, P5 1/4): it drops
terms, makes arithmetic errors, and uses an error-prone `f(k,S)−f(k−1,S)`
decomposition that compounds mistakes. Opus/sonnet use the closed form and
self-check via the s↔9n−s symmetry → 100%.

**Why this is not cheating:** identical fair prompts, objective brute-forced ground
truth, unmodified models (no persona, no induced handicap), no tooling artifact. The
gap is *variance/reliability*, surfaced by sampling — not a single lucky/unlucky run.

**The audit consequence (quality-routing on a real gap):** for the counting
competency, correctness ties (1.00/1.00/0.65) hide the signal in one shot; the
reliability lens separates them (discrimination = 0.35 item-level, 0.75
trial-level). Audit-hire routes counting to the cheapest **reliable** passer —
**sonnet** (100%, cheaper than opus) — rejects **haiku** there (65% → ships a wrong
count ~1 run in 3), and still uses cheap haiku on competencies where it's reliable.
That beats always-haiku on quality (1.00 vs 0.65) and always-opus on cost — the full
thesis, now on a **naturally-occurring** gap rather than an induced one.
Data: `experiments/results/reliability_sweep.md`. Broader synthesis and application
proposal: `docs/FINDINGS_AND_OPEN_PROBLEMS.md`.

---

## Run 4 — honest attempt at a NATURAL quality gap (null result), 2026-07

Run 3's weak agent was *induced* (a persona). Run 4 asks the harder, honest question:
do **unmodified** opus / sonnet / haiku differ in *correctness* on genuinely hard,
unambiguous coding tasks — no personas, same fair spec? Two LeetCode-hard problems:
`calculate` (basic calculator with parentheses + precedence + truncating division) and
`is_match` (regex with `.`/`*`, full-string), graded with brutal edge-case suites.

**Result: no. All three pass everything** — 12/12 on `calculate`, 15/15 on `is_match`.
Frontier models do not separate on correctness on well-known hard problems.

Two **false** spreads appeared first and were **rejected as tooling artifacts**, not
reported as findings (this is what "don't cheat" looks like in practice):
- opus's `is_match` used `from functools import lru_cache` — the sandbox blocked *all*
  imports, so a correct solution scored 0.00. **Fix:** allow a safe stdlib allowlist
  (functools, collections, math, …); still block os/sys/subprocess/socket.
- haiku's `calculate` used recursion for parentheses — the sandbox exec'd with separate
  globals/locals, so the function couldn't see itself (`NameError`), scoring 0.58.
  **Fix:** exec in a single namespace so recursion / cross-function references work.

Both were genuine methodology bugs (now covered by tests); after fixing them the honest
answer is a clean 3-way tie.

**Conclusion:** a *natural* correctness gap needs either a genuinely weaker model than
any available here, or novel/adversarial tasks outside these models' competence —
neither obtainable via the free subagent path. Among opus/sonnet/haiku, the honest
differentiator is **cost/efficiency, not quality** (runs 1-2), unless a genuinely weak
agent is in the pool (run 3, induced). We did not manufacture a quality gap.

---

## Run 3 — quality-routing FIRES (real models, free), 2026-07

Runs 1-2 showed the cost win but never the quality win (frontier models passed
everything). Run 3 adds a deliberately weak-but-cheapest agent, **nano** (haiku with a
fast/terse persona + a minimal no-edge-case spec), to the pool. nano is real and mostly
competent — but its `merge` returns tuples instead of lists, so it fails the `intervals`
competency while passing `parsing`. Screening and held-out job use *different test
instances* of each competency; all code graded in the subprocess sandbox
(`experiments/subagent_run_quality_routing.py`).

**Correctness (screening / held-out job):**

| competency | opus | haiku | nano |
|---|---|---|---|
| intervals | 1.00 / 1.00 | 1.00 / 1.00 | **0.00 / 0.00** |
| parsing | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |

Intervals screening **discrimination = 1.00** (the audit separates them). The audit
hires a **mixed team**: `intervals -> haiku` (nano fails), `parsing -> nano` (cheapest,
all pass).

**Held-out job — quality and cost:**

| strategy | quality | cost $ | |
|---|---|---|---|
| **audit_hire** | **1.00** | **0.12** | mixed team (haiku + nano) |
| always_haiku | 1.00 | 0.21 | same quality, higher cost |
| always_opus | 1.00 | 1.08 | naive "always biggest" |
| always_nano | **0.50** | 0.04 | naive "always cheapest" — fails intervals |

**This is the full thesis, demonstrated on real models:**
- ✅ **Beats "always cheapest" on QUALITY** — 1.00 vs 0.50. The audit caught that nano is
  broken on `intervals` and routed around it; the naive cheap policy ships the bug.
- ✅ **Beats "always biggest" on COST** — 9× cheaper, same quality.
- ✅ **Beats "always haiku" on cost** at equal quality, by using cheap nano for the one
  competency where it's sufficient (mixed team).

audit_hire is the **only** strategy that achieves perfect quality at the lowest cost.
The quality-routing claim — untriggered in runs 1-2 — now holds: a per-requirement audit
lets you safely exploit a cheap agent *where it works* and route around it *where it
doesn't*, which neither "always cheapest" nor "always biggest" can do.

*Caveat: nano is a constructed weak agent (a real model given a terse persona), and its
failure is a type bug rather than a deep capability gap; the mechanism is what's shown.
The faithful paid run would use genuinely distinct model tiers.*

---

## Run 2 — agentic/executable, real-model (free via subagents), 2026-07

Validated the **agentic** path for free (session models, no API spend), per the
"prove it before you pay" principle. `opus`/`sonnet`/`haiku` each wrote real code for
a screening audit (`merge`, `decode`) and a **held-out** job (`insert`, `evaluate`),
graded in the subprocess sandbox; effort = real subagent tokens × output price
(`experiments/subagent_run_agentic.py`).

**All three models passed every hidden test on all four tasks** — including the hard
`evaluate` (operator precedence) and the interval edge cases. So, again, correctness
does not discriminate them. Held-out job:

| strategy | quality | efficiency | cost $ |
|---|---|---|---|
| **audit_hire** | 1.00 | 1.00 | **0.21** |
| always_haiku | 1.00 | 1.00 | 0.21 |
| always_sonnet | 1.00 | 0.25 | 0.81 |
| always_opus | 1.00 | 0.19 | 1.08 |

**audit-hire matched the best model's quality at ~1/5 the cost of always-opus**, by
screening-then-certifying that haiku is sufficient for both competencies. It ties
always-haiku here (both use haiku) — but with a *guarantee* from the audit rather than
a blind bet. Correctness discrimination on the hardest task (`evaluate`): **0.00**.

**Honest status of the two claims:**
- ✅ **Cost claim — demonstrated twice** (text run 1, agentic run 2): a per-task audit
  lets you hire the cheapest *sufficient* model and match top-tier quality at a
  fraction of the cost. This is the FrugalGPT result, but driven by a requirement-
  specific audit rather than an offline classifier, and it now holds on executable
  code tasks, not just text.
- ⏳ **Quality-routing claim — still untriggered.** Because frontier models pass these
  tasks, the "weak model fails a competency → audit reroutes to a stronger one → beats
  always-cheapest" case never fired. Demonstrating it needs genuinely *discriminating*
  tasks (adversarial edge cases, or a much weaker candidate in the pool). This is the
  single most important next experiment — and it's exactly what the adaptive
  discrimination loop (`adaptive.py`) exists to search for.

---

# Earlier results

## Run 1 — `claim_verification`, real-model approximation (2026-07)

**Setup.** This sandbox had no standalone API key, so candidate answers were produced
by real Claude models through the Claude Code subagent mechanism: `opus` (~opus-4-8),
`sonnet` (~sonnet-5), `haiku` (~haiku-4-5). Each model answered the **screening
audit** and the **held-out job tasks** in separate, isolated runs. The screening
audit used a *different* source document (a library report) than the job (a transit
report), so the job was genuinely held out. Grading, hiring, and the cost comparison
were computed by the real `agent_audit` code offline
(`experiments/subagent_run_claim_verification.py`).

**Caveats — this is directional, not the clean study.** Only 3 model tiers, not the
faithful 4-model policy (no `*-4-6` variants). `opus` also stood in as
strategist/judge, so author/candidate separation was not controlled. The faithful,
publishable run is `experiments/run_harness.py` with a real API key.

### Screening (audit) — competency scores

| candidate | overall | claim_verification | hallucination_resistance | numeric_reasoning | hired |
|---|---|---|---|---|---|
| opus | 1.00 | 1.00 | 1.00 | 1.00 | ✅ |
| sonnet | 1.00 | 1.00 | 1.00 | 1.00 | ✅ |
| haiku | 1.00 | 1.00 | 1.00 | 1.00 | ✅ |

### Held-out job — quality and relative cost (haiku = 1×)

| strategy | job score | rel. cost |
|---|---|---|
| **audit_hire** | **1.00** | **1.0×** |
| cheapest_model (haiku) | 1.00 | 1.0× |
| leaderboard_pick (sonnet) | 1.00 | 3.0× |
| biggest_model (opus) | 1.00 | 5.0× |

### What this shows — and what it doesn't

- **The honest headline: audit-hire matched the biggest model's quality (100%) at
  1/5 the cost.** Because all three tiers aced the screening audit, the pipeline
  (with cost-aware tie-breaking) certified that **haiku is sufficient** and hired it,
  rather than defaulting to opus. That is the FrugalGPT-style win — but driven by a
  *task-specific audit* the strategist authored, not an offline classifier.
- **This case did NOT discriminate the models on quality.** All three got every item
  right, on both the audit and the job. So this run does *not* demonstrate the other
  half of the thesis — that when a weak model fails a competency, the audit reroutes
  that role to a stronger model (where always-cheapest would fail). Here, audit_hire
  and cheapest_model are indistinguishable on quality; the audit's contribution is a
  **guarantee** that cheapest is safe, versus a gamble.
- **What the experiment motivated (and we added):** cost-aware tie-breaking in
  `form_team` — when candidates tie on a competency, hire the cheapest passer. Without
  it, audit-hire would have defaulted to opus and shown no benefit over
  `biggest_model`.

### Addendum — the tie was a scoring artifact, not a real tie

The "3-way tie" above came from a **correctness-only** rubric. Re-scoring the exact
same real-model answers with **efficiency** (correctness × cost, cheapest-correct
wins — `experiments/rescore_efficiency.py`) recovers a strong signal:

| candidate | correct | tokens | cost $ | efficiency |
|---|---|---|---|---|
| opus | 1.00 | 22030 | 0.5507 | 0.19 |
| sonnet | 1.00 | 27453 | 0.4118 | 0.25 |
| **haiku** | 1.00 | 20840 | 0.1042 | **1.00** |

- discrimination (correctness-only): **0.00** — no hiring signal
- discrimination (efficiency): **0.81** — separated; hires **haiku** (correct *and*
  cheapest path)

So the strategist's job is twofold: (1) design items difficult enough to separate
candidates, and (2) score the **shortest / cheapest path to a correct answer**, not
just correctness. Under (2), even an "easy" task discriminates — you're measuring
capability *per unit cost*, which is exactly the trait being hired for. (Token counts
here are rough subagent totals; a clean run instruments per-task model tokens.)

### Next run needed to test the harder claim

To show the **quality-routing** benefit (not just the cost benefit), we need a case
with genuine spread — items a strong model passes and a weak one fails. Candidates:
`policy_faithful_support` (the day-70 "nothing after 60 days" edge and the
legal-advice refusal are the kind of thing a small model is likelier to get wrong) or
harder, adversarial `claim_verification` items (subtle multi-hop contradictions,
injected instructions inside the source). Expected shape of a positive result:
audit_hire ties `biggest_model` on quality while beating it on cost, *and* beats
`cheapest_model` on quality.
