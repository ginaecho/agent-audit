"""End-to-end tests for the audit-driven hiring pipeline (fully offline)."""

from __future__ import annotations

import json

import pytest

from agent_audit import AuditPipeline, MockProvider
from agent_audit.demo import build_demo
from agent_audit.grader import Grader
from agent_audit.models import Check, TestCase


# --- Full pipeline via the built-in demo -------------------------------------


@pytest.fixture(scope="module")
def demo_run():
    pipeline, requirement, candidates = build_demo()
    return pipeline.run(requirement, candidates)


def test_strategist_produces_a_usable_audit(demo_run):
    audit = demo_run.audit
    assert audit.test_cases, "audit should contain test cases"
    assert set(audit.competencies) == {"refund_policy", "json_lookup", "legal_refusal"}
    # Every case is tagged with a declared competency.
    for tc in audit.test_cases:
        assert tc.competency in audit.competencies


def test_strong_candidate_is_hired_weak_is_not(demo_run):
    by_name = {r.candidate: r for r in demo_run.reports}
    assert by_name["acme-generalist"].hired is True
    assert by_name["budget-bot"].hired is False
    # The strong generalist should clearly outscore the weak bot.
    assert by_name["acme-generalist"].overall_score > by_name["budget-bot"].overall_score


def test_specialist_wins_its_role_even_if_not_overall_lead(demo_run):
    team = demo_run.team
    roles = {a.competency: a.candidate for a in team.assignments}
    # The json-specialist emits perfect (fenced) JSON, so it should staff json_lookup.
    assert roles["json_lookup"] == "json-specialist"
    # The lead is the best *overall* hire — the generalist here.
    assert team.lead == "acme-generalist"


def test_weak_candidate_never_staffs_a_role(demo_run):
    team = demo_run.team
    assert "budget-bot" not in {a.candidate for a in team.assignments}


def test_run_artifact_is_json_serializable(demo_run):
    blob = json.dumps(demo_run.to_dict(), default=str)
    assert '"hired"' in blob
    assert "acme-generalist" in blob


# --- Grader unit checks ------------------------------------------------------


@pytest.fixture
def grader():
    return Grader(judge=None)


def _case(*checks):
    return TestCase(id="t", competency="c", prompt="p", checks=list(checks))


def test_contains_check(grader):
    res = grader.grade_case(_case(Check(type="contains", value="hello")), "well hello there")
    assert res.score == 1.0
    res = grader.grade_case(_case(Check(type="contains", value="goodbye")), "well hello there")
    assert res.score == 0.0


def test_json_path_equals_handles_fenced_json(grader):
    check = Check(type="json_path_equals", path="status", value="shipped")
    answer = '```json\n{"order_id": "A-1", "status": "shipped"}\n```'
    assert grader.grade_case(_case(check), answer).score == 1.0


def test_numeric_close_check(grader):
    check = Check(type="numeric_close", value=42.0, tolerance=0.5)
    assert grader.grade_case(_case(check), "the answer is 42").score == 1.0
    assert grader.grade_case(_case(check), "the answer is 99").score == 0.0


def test_not_contains_check(grader):
    check = Check(type="not_contains", value="you should sue")
    assert grader.grade_case(_case(check), "please consult a lawyer").score == 1.0
    assert grader.grade_case(_case(check), "honestly you should sue them").score == 0.0


def test_llm_judge_check_is_skipped_without_a_judge(grader):
    # A judge check with no judge configured is excluded from the score, not counted 0.
    res = grader.grade_case(
        _case(
            Check(type="contains", value="ok"),
            Check(type="llm_judge", rubric="is it polite?"),
        ),
        "ok sure",
    )
    assert res.score == 1.0  # only the objective check counts
    assert any(cr.detail.startswith("SKIPPED") for cr in res.check_results)


def test_candidate_that_raises_fails_the_case():
    def boom(prompt, system=None):
        raise RuntimeError("model unavailable")

    pipeline = AuditPipeline(
        strategist=MockProvider("s", json.dumps({
            "summary": "s",
            "competencies": ["c"],
            "test_cases": [{
                "competency": "c",
                "prompt": "hi",
                "checks": [{"type": "contains", "value": "x"}],
            }],
        })),
    )
    run = pipeline.run("req", [MockProvider("broken", boom)])
    report = run.reports[0]
    assert report.overall_score == 0.0
    assert report.hired is False
    assert report.case_results[0].error
