"""Offline tests for the audit-vs-baselines evaluation harness."""

from __future__ import annotations

import json

from agent_audit import (
    AuditPipeline,
    Harness,
    JobTask,
    MockProvider,
    RequirementCase,
)
from agent_audit.models import Check

# Audit with the same competency vocabulary as the case's job tasks.
_AUDIT_JSON = json.dumps({
    "summary": "math + formatting",
    "competencies": ["arithmetic", "formatting"],
    "pass_threshold": 0.6,
    "competency_threshold": 0.5,
    "test_cases": [
        {
            "competency": "arithmetic",
            "prompt": "What is 17 + 25? Number only.",
            "checks": [{"type": "numeric_close", "value": 42}],
        },
        {
            "competency": "formatting",
            "prompt": "Return ONLY JSON {\"ok\": true}.",
            "checks": [{"type": "json_valid"},
                       {"type": "json_path_equals", "path": "ok", "value": True}],
        },
    ],
})

CASE = RequirementCase(
    name="mini",
    requirement="Do arithmetic and emit clean JSON.",
    job_tasks=[
        JobTask(id="j1", competency="arithmetic", prompt="What is 100 - 58? Number only.",
                checks=[Check(type="numeric_close", value=42)]),
        JobTask(id="j2", competency="formatting",
                prompt="Return ONLY JSON {\"done\": true}.",
                checks=[Check(type="json_valid"),
                        Check(type="json_path_equals", path="done", value=True)]),
    ],
)


def _mathbot(prompt: str, system: str | None) -> str:
    # Great at arithmetic, hopeless at JSON.
    return "42" if "Number only" in prompt else "sure, done!"


def _jsonbot(prompt: str, system: str | None) -> str:
    # Great at JSON, hopeless at arithmetic.
    if "ONLY JSON" in prompt:
        return '{"ok": true}' if '"ok"' in prompt else '{"done": true}'
    return "I think it's about a hundred?"


def _dud(prompt: str, system: str | None) -> str:
    return "no idea"


def _make_harness():
    mathbot = MockProvider("mathbot", _mathbot)
    jsonbot = MockProvider("jsonbot", _jsonbot)
    dud = MockProvider("dud", _dud)
    pipeline = AuditPipeline(strategist=MockProvider("strategist", _AUDIT_JSON))
    return Harness(
        pipeline=pipeline,
        grader=pipeline.grader,
        candidates=[mathbot, jsonbot, dud],
        baselines={"dud_baseline": dud, "mathbot_only": mathbot},
    )


def test_audit_hire_routes_each_job_task_to_its_specialist():
    report = _make_harness().run_case(CASE)
    by_name = {s.strategy: s for s in report.strategies}
    treat = by_name["audit_hire"]
    # Each specialist should be routed the task it is provably good at...
    assert "arithmetic->mathbot" in treat.executor
    assert "formatting->jsonbot" in treat.executor
    # ...so the team aces the held-out job, beating every single-model baseline.
    assert treat.job_score == 1.0
    assert treat.job_score > by_name["dud_baseline"].job_score
    assert treat.job_score > by_name["mathbot_only"].job_score


def test_single_baseline_scores_reflect_partial_competence():
    report = _make_harness().run_case(CASE)
    by_name = {s.strategy: s for s in report.strategies}
    assert by_name["mathbot_only"].job_score == 0.5   # wins math task, fails JSON task
    assert by_name["dud_baseline"].job_score == 0.0


def test_harness_report_serializes_and_summarizes():
    harness = _make_harness()
    report = harness.run([CASE])
    blob = json.dumps(report.to_dict(), default=str)
    assert "audit_hire" in blob
    text = report.summary()
    assert "Mean job score" in text and "audit_hire" in text
