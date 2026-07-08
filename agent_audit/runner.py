"""Run an audit against a candidate and aggregate the score into a report."""

from __future__ import annotations

import time

from .grader import Grader
from .models import AuditSpec, CandidateReport, CaseResult
from .providers import Provider


class Runner:
    def __init__(self, grader: Grader) -> None:
        self.grader = grader

    def run(self, audit: AuditSpec, candidate: Provider) -> CandidateReport:
        case_results: list[CaseResult] = []
        for test_case in audit.test_cases:
            start = time.monotonic()
            error = ""
            try:
                response = candidate.complete(test_case.prompt)
            except Exception as exc:  # a candidate that crashes simply fails the item
                response, error = "", f"{type(exc).__name__}: {exc}"
            latency = time.monotonic() - start
            case_results.append(
                self.grader.grade_case(test_case, response, latency_s=latency, error=error)
            )

        overall = _weighted_overall(case_results)
        competency_scores = _competency_scores(audit, case_results)
        return CandidateReport(
            candidate=candidate.name,
            overall_score=overall,
            competency_scores=competency_scores,
            case_results=case_results,
        )


def _weighted_overall(case_results: list[CaseResult]) -> float:
    total_w = sum(r.test_case.weight for r in case_results)
    if not total_w:
        return 0.0
    return sum(r.score * r.test_case.weight for r in case_results) / total_w


def _competency_scores(audit: AuditSpec, case_results: list[CaseResult]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for competency in audit.competencies:
        rows = [r for r in case_results if r.test_case.competency == competency]
        total_w = sum(r.test_case.weight for r in rows)
        scores[competency] = (
            sum(r.score * r.test_case.weight for r in rows) / total_w if total_w else 0.0
        )
    return scores
