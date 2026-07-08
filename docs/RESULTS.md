# Results

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

### Next run needed to test the harder claim

To show the **quality-routing** benefit (not just the cost benefit), we need a case
with genuine spread — items a strong model passes and a weak one fails. Candidates:
`policy_faithful_support` (the day-70 "nothing after 60 days" edge and the
legal-advice refusal are the kind of thing a small model is likelier to get wrong) or
harder, adversarial `claim_verification` items (subtle multi-hop contradictions,
injected instructions inside the source). Expected shape of a positive result:
audit_hire ties `biggest_model` on quality while beating it on cost, *and* beats
`cheapest_model` on quality.
