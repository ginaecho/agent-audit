"""Offline tests for the audit -> coach -> improve -> re-audit loop."""

from __future__ import annotations

import json

from agent_audit import AuditPipeline, Coach, MockProvider, SkilledProvider

# A two-competency audit the mock strategist "authors".
_AUDIT_JSON = json.dumps({
    "summary": "extraction + verdict discipline",
    "competencies": ["json_extraction", "claim_verification"],
    "pass_threshold": 0.7,
    "competency_threshold": 0.5,
    "test_cases": [
        {
            "competency": "json_extraction",
            "prompt": "Return ONLY JSON with keys id (string 'X-1') and status ('open').",
            "checks": [
                {"type": "json_valid"},
                {"type": "json_path_equals", "path": "id", "value": "X-1"},
                {"type": "json_path_equals", "path": "status", "value": "open"},
            ],
        },
        {
            "competency": "claim_verification",
            "prompt": "Source says revenue fell. Claim: 'revenue rose'. Verdict?",
            "checks": [
                {"type": "regex", "value": r"\bCONTRADICTED\b",
                 "description": "explicit verdict word"},
            ],
        },
    ],
})


def _coachable_agent(prompt: str, system: str | None) -> str:
    """Agent A: sloppy by default. But it *reads its skill*: once the coach's
    skill text (delivered via system) tells it to return only JSON / give explicit
    verdicts, it complies — modelling a real model following better instructions."""
    skilled = bool(system) and "SKILL:" in system
    if "ONLY JSON" in prompt:
        if skilled and "JSON" in system:
            return '{"id": "X-1", "status": "open"}'
        return "The id is X-1 and the status is open."  # prose, fails JSON checks
    if "Verdict" in prompt:
        if skilled and ("verdict" in system.lower() or "unambiguous" in system.lower()):
            return "CONTRADICTED — the source states revenue fell."
        return "Hmm, the claim seems off given the source."  # no explicit verdict
    return "ok"


def _make_pipeline() -> AuditPipeline:
    return AuditPipeline(strategist=MockProvider("strategist", _AUDIT_JSON))


def test_coach_produces_plan_with_skill_text_from_failures():
    pipeline = _make_pipeline()
    agent_a = MockProvider("agent-a", _coachable_agent)
    run_a = pipeline.run("req", [agent_a])
    report_a = run_a.reports[0]
    assert report_a.hired is False

    plan = Coach().improvement_plan(run_a.audit, report_a)  # deterministic, no LLM
    assert plan.candidate == "agent-a"
    assert {g.competency for g in plan.guidance} == {"json_extraction", "claim_verification"}
    assert "SKILL:" in plan.skill_text
    assert "JSON" in plan.skill_text
    # Guidance generalizes; it must not leak the literal expected answer values.
    assert '"X-1"' not in plan.skill_text.replace("'", '"') or "id" not in plan.skill_text


def test_same_audit_measures_uplift_after_coaching():
    pipeline = _make_pipeline()
    agent_a = MockProvider("agent-a", _coachable_agent)
    run_a = pipeline.run("req", [agent_a])
    audit = run_a.audit
    report_a = run_a.reports[0]

    plan = Coach().improvement_plan(audit, report_a)
    agent_b = SkilledProvider(agent_a, plan.skill_text, name="agent-b")

    # Re-certification path: the SAME audit, not a fresh exam.
    run_b = pipeline.run("req", [agent_b], audit=audit)
    report_b = run_b.reports[0]

    assert report_b.overall_score > report_a.overall_score
    assert report_b.hired is True
    for comp in audit.competencies:
        assert report_b.competency_scores[comp] >= report_a.competency_scores[comp]


def test_strong_candidate_gets_empty_plan():
    pipeline = _make_pipeline()
    perfect = MockProvider(
        "perfect",
        lambda p, s: ('{"id": "X-1", "status": "open"}' if "ONLY JSON" in p
                      else "CONTRADICTED — the source says revenue fell."),
    )
    run = pipeline.run("req", [perfect])
    plan = Coach().improvement_plan(run.audit, run.reports[0])
    assert plan.guidance == []
    assert plan.skill_text == ""
