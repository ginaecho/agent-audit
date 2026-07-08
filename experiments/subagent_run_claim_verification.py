"""Real-model approximation of the harness on the `claim_verification` case.

Because this sandbox exposes no standalone API key, the candidate answers below were
produced by real Claude models via the Claude Code subagent mechanism (2026-07):
`opus` (~opus-4-8), `sonnet` (~sonnet-5), `haiku` (~haiku-4-5). Each model answered
the screening audit and the held-out job tasks in SEPARATE, isolated runs. Grading,
hiring, and the cost comparison below use the real `agent_audit` code offline.

Caveats (this is directional, not the clean study):
  * only 3 tiers, not the exact 4-model policy (no *-4-6 variants);
  * `opus` here also plays strategist/judge, so author/candidate overlap is not
    controlled — the faithful run (experiments/run_harness.py) fixes this.

Run:  python experiments/subagent_run_claim_verification.py
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_audit.grader import Grader
from agent_audit.hiring import decide_hiring, form_team
from agent_audit.models import AuditSpec, CandidateReport, Check, TestCase
from agent_audit.runner import _competency_scores, _weighted_overall

# Output $/Mtok, used only for the relative-cost comparison and tie-breaking.
COST = {"opus": 25.0, "sonnet": 15.0, "haiku": 5.0}

# --- The screening audit the strategist (opus-4-8) authored --------------------
# Uses a DIFFERENT source (library report) than the job (transit report), so the
# job stays genuinely held out.
_S = ("Library annual report (2025): Total visits were 220,000, up from 180,000 in "
      "2024. E-book loans made up 35% of all loans. The library ran a deficit of "
      "$50,000, covered by reserves. A new branch is under consideration.")

AUDIT = AuditSpec(
    requirement="research verifier: SUPPORTED / CONTRADICTED / NOT STATED, no fabrication",
    summary="Screens verifiers for correct verdicts, hallucination resistance, and arithmetic.",
    competencies=["claim_verification", "hallucination_resistance", "numeric_reasoning"],
    test_cases=[
        TestCase("ac1", "claim_verification", f"{_S}\nClaim: 'Total visits increased.' Verdict?",
                 [Check(type="regex", value=r"\bSUPPORTED\b")]),
        TestCase("ac2", "claim_verification",
                 f"{_S}\nClaim: 'E-book loans were the majority.' Verdict?",
                 [Check(type="regex", value=r"\bCONTRADICTED\b"),
                  Check(type="contains", value="35")]),
        TestCase("ac3", "hallucination_resistance",
                 f"{_S}\nClaim: 'The new branch will open in 2026.' Verdict?",
                 [Check(type="regex", value=r"NOT[ _]STATED"),
                  Check(type="not_contains", value="supported")]),
        TestCase("ac4", "numeric_reasoning", f"{_S}\nHow many more visits in 2025? Number only.",
                 [Check(type="numeric_close", value=40000, tolerance=0.01)]),
    ],
)

# --- The held-out job tasks (transit source) ----------------------------------
_J = ("Excerpt — city transit annual report (2025): Ridership recovered to 61 million "
      "trips in 2025, up from 48 million in 2024 but still below the 2019 peak of 74 "
      "million. The Green Line accounted for 38% of all trips. Fare revenue covered "
      "43% of operating costs; the remainder came from the municipal subsidy. Two new "
      "tram lines are planned, with construction starting 2027.")

JOB = [
    TestCase("job_claim_supported", "claim_verification",
             f"{_J}\nClaim: 'Ridership 2025 > 2024 but below 2019 peak.' Verdict?",
             [Check(type="regex", value=r"\bSUPPORTED\b"),
              Check(type="not_contains", value="contradicted")]),
    TestCase("job_claim_contradicted", "claim_verification",
             f"{_J}\nClaim: 'Fare revenue covered the majority of operating costs.' Verdict?",
             [Check(type="regex", value=r"\bCONTRADICTED\b"), Check(type="contains", value="43")]),
    TestCase("job_claim_notstated", "hallucination_resistance",
             f"{_J}\nClaim: 'The Green Line was the most profitable line.' Verdict?",
             [Check(type="regex", value=r"NOT[ _]STATED"),
              Check(type="not_contains", value="supported,")]),
    TestCase("job_extract_figure", "numeric_reasoning",
             f"{_J}\nHow many MORE trips in 2025 than 2024, in millions? Number only.",
             [Check(type="numeric_close", value=13, tolerance=0.01)]),
]

# --- Verbatim real-model answers (from the subagent runs) ---------------------
AUDIT_ANSWERS = {
    "opus": {"ac1": "SUPPORTED. The source states \"Total visits were 220,000, up from 180,000 in 2024.\"",
             "ac2": "CONTRADICTED. The source states \"E-book loans made up 35% of all loans,\" which is not a majority.",
             "ac3": "NOT STATED. The source only says \"A new branch is under consideration,\" with no mention of a 2026 opening.",
             "ac4": "40000"},
    "sonnet": {"ac1": "SUPPORTED: The source states \"Total visits were 220,000, up from 180,000 in 2024,\" confirming an increase.",
               "ac2": "CONTRADICTED: The source states \"E-book loans made up 35% of all loans,\" which is a minority, not a majority.",
               "ac3": "NOT STATED: The source only says \"A new branch is under consideration,\" with no mention of an opening date.",
               "ac4": "40000"},
    "haiku": {"ac1": "SUPPORTED - Total visits were 220,000, up from 180,000 in 2024.",
              "ac2": "CONTRADICTED - E-book loans made up 35% of all loans, which is not a majority.",
              "ac3": "NOT STATED - The report states a new branch is under consideration but provides no information about when it will open.",
              "ac4": "40000"},
}
JOB_ANSWERS = {
    "opus": {"job_claim_supported": "SUPPORTED: The source states \"Ridership recovered to 61 million trips in 2025, up from 48 million in 2024 but still below the 2019 peak of 74 million.\"",
             "job_claim_contradicted": "CONTRADICTED: The source states \"Fare revenue covered 43% of operating costs; the remainder came from the municipal subsidy,\" meaning fare revenue covered less than half, not the majority.",
             "job_claim_notstated": "NOT STATED: The source says \"The Green Line accounted for 38% of all trips\" but says nothing about profitability of any line.",
             "job_extract_figure": "13"},
    "sonnet": {"job_claim_supported": "SUPPORTED: The source states \"Ridership recovered to 61 million trips in 2025, up from 48 million in 2024 but still below the 2019 peak of 74 million,\" which directly matches the claim.",
               "job_claim_contradicted": "CONTRADICTED: The source states \"Fare revenue covered 43% of operating costs,\" which is a minority share, not the majority claimed.",
               "job_claim_notstated": "NOT STATED: The source only says \"The Green Line accounted for 38% of all trips\" and gives no information about profitability of any line.",
               "job_extract_figure": "13"},
    "haiku": {"job_claim_supported": "SUPPORTED: Source states 'Ridership recovered to 61 million trips in 2025, up from 48 million in 2024 but still below the 2019 peak of 74 million.'",
              "job_claim_contradicted": "CONTRADICTED: Source states 'Fare revenue covered 43% of operating costs' which is not a majority.",
              "job_claim_notstated": "NOT STATED: Source only mentions Green Line accounted for 38% of trips with no information about profitability.",
              "job_extract_figure": "13"},
}

MODELS = ["opus", "sonnet", "haiku"]


def _score(tasks, answers):
    grader = Grader(judge=None)  # every check here is deterministic
    results = [grader.grade_case(tc, answers[tc.id]) for tc in tasks]
    return results


def main() -> int:
    # 1. Screen candidates on the audit -> reports -> hire.
    reports = []
    for m in MODELS:
        cases = _score(AUDIT.test_cases, AUDIT_ANSWERS[m])
        reports.append(CandidateReport(
            candidate=m, overall_score=_weighted_overall(cases),
            competency_scores=_competency_scores(AUDIT, cases), case_results=cases))
    decide_hiring(AUDIT, reports)
    team = form_team(AUDIT, reports, cost=COST)   # cost-aware tie-break

    print("SCREENING (audit) — competency scores")
    for r in reports:
        cs = "  ".join(f"{k}:{v:.2f}" for k, v in r.competency_scores.items())
        print(f"  {r.candidate:<8} overall {r.overall_score:.2f}  hired={r.hired}  [{cs}]")
    print("\nHIRED TEAM (cost-aware)")
    print(f"  lead: {team.lead}")
    for a in team.assignments:
        print(f"    {a.competency:<24} -> {a.candidate}   ({a.reason})")

    # 2. Job scores per model.
    job = {m: _score(JOB, JOB_ANSWERS[m]) for m in MODELS}
    job_score = {m: _weighted_overall(job[m]) for m in MODELS}

    # 3. Strategy comparison on the held-out job.
    def route(competency):
        for a in team.assignments:
            if a.competency == competency and a.candidate:
                return a.candidate
        return team.lead

    tasks_by_id = {tc.id: tc for tc in JOB}
    grader = Grader(judge=None)
    audit_hire_per = {}
    audit_hire_cost = 0.0
    for tc in JOB:
        m = route(tc.competency)
        audit_hire_per[tc.id] = grader.grade_case(tc, JOB_ANSWERS[m][tc.id]).score
        audit_hire_cost += COST[m]
    audit_hire = _weighted_from(JOB, audit_hire_per)

    n = len(JOB)
    strategies = {
        "audit_hire": (audit_hire, audit_hire_cost),
        "biggest_model (opus)": (job_score["opus"], n * COST["opus"]),
        "leaderboard_pick (sonnet)": (job_score["sonnet"], n * COST["sonnet"]),
        "cheapest_model (haiku)": (job_score["haiku"], n * COST["haiku"]),
    }
    base = n * COST["haiku"]
    print("\nHELD-OUT JOB — quality and relative cost")
    print(f"  {'strategy':<28} {'job score':>9} {'rel. cost':>10}")
    for name, (q, c) in sorted(strategies.items(), key=lambda kv: (-kv[1][0], kv[1][1])):
        print(f"  {name:<28} {q:>9.2f} {c / base:>9.1f}x")
    return 0


def _weighted_from(tasks, per):
    tw = sum(t.weight for t in tasks)
    return sum(per.get(t.id, 0.0) * t.weight for t in tasks) / tw if tw else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
