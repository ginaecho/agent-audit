"""Coaching: turn a candidate's audit results into improvement guidance.

The audit is not only a gate — it is a diagnosis. For every competency where a
candidate under-performed, the coach collects the concrete failures (which check,
what was expected, what the candidate actually said) and turns them into an
``ImprovementPlan``:

* a human-readable report of *why* the candidate scored what it scored, and
* ``skill_text`` — a distilled instruction block that can be attached to the agent
  (``SkilledProvider(agent, plan.skill_text)``) to produce an improved agent.

That closes the loop the audit implies: **audit agent A -> coach -> attach skill ->
agent B -> re-audit -> the same exam measures the uplift.** Improving an agent's
skills *is* a hiring path, and the audit is the instrument that both guides and
verifies it.

Guidance generation is deterministic by default (composed from the failed checks
themselves, so it runs offline). Pass a ``coach`` provider — ideally the strategist
model — to have an LLM write sharper, more general advice from the same evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import AuditSpec, CandidateReport, CaseResult, Check
from .providers import Provider

COACH_SYSTEM = """\
You are the Coach in an agent-hiring pipeline. A candidate agent was audited and
under-performed on some competencies. You receive the concrete evidence: each failed
check, what it expected, and what the candidate actually answered.

Write improvement guidance for the candidate as a SKILL — a concise instruction block
that will be prepended to the agent's system prompt on future tasks. Rules:
- Generalize from the evidence: teach the behavior, don't leak the literal test
  answers (never say "answer 'X' to question Y"; say "always cite the policy window
  when denying a request").
- Be imperative and specific ("Return ONLY a JSON object with exactly the requested
  keys"), not vague ("be more careful").
- One short bullet per lesson, grouped by competency. No preamble, no commentary.
Return only the skill text.\
"""


@dataclass
class Failure:
    """One failed (or partially failed) check, with its evidence."""

    case_id: str
    competency: str
    prompt: str
    check_description: str
    check_type: str
    expected: str
    detail: str
    response_excerpt: str


@dataclass
class CompetencyGuidance:
    competency: str
    score: float
    failures: list[Failure]
    advice: str = ""


@dataclass
class ImprovementPlan:
    candidate: str
    guidance: list[CompetencyGuidance]
    skill_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        lines = [f"Improvement plan for {self.candidate}:"]
        for g in self.guidance:
            lines.append(f"  {g.competency} (scored {g.score:.2f}) — {len(g.failures)} failure(s)")
            for line in g.advice.splitlines():
                if line.strip():
                    lines.append(f"    • {line.strip().lstrip('-• ')}")
        return "\n".join(lines)


class Coach:
    def __init__(self, coach: Provider | None = None) -> None:
        self.coach = coach

    def improvement_plan(
        self,
        audit: AuditSpec,
        report: CandidateReport,
        *,
        max_competency_score: float | None = None,
    ) -> ImprovementPlan:
        """Build guidance for every competency scoring below the staffing bar.

        ``max_competency_score`` overrides which competencies count as weak
        (default: anything below the audit's ``competency_threshold`` — plus any
        competency with at least one outright failed check, since even a passer
        can be tightened).
        """
        bar = (
            max_competency_score
            if max_competency_score is not None
            else audit.competency_threshold
        )
        guidance: list[CompetencyGuidance] = []
        for competency in audit.competencies:
            score = report.competency_scores.get(competency, 0.0)
            failures = _collect_failures(report.case_results, competency)
            if score >= bar and not failures:
                continue
            if not failures:
                continue
            advice = self._advise(competency, failures)
            guidance.append(CompetencyGuidance(competency, score, failures, advice))

        skill_text = _render_skill(report.candidate, guidance) if guidance else ""
        return ImprovementPlan(candidate=report.candidate, guidance=guidance,
                               skill_text=skill_text)

    def _advise(self, competency: str, failures: list[Failure]) -> str:
        if self.coach is not None:
            evidence = "\n\n".join(
                f"FAILED CHECK ({f.check_type}): {f.check_description or f.expected}\n"
                f"expected: {f.expected}\n"
                f"grader detail: {f.detail}\n"
                f"candidate answered: {f.response_excerpt}"
                for f in failures
            )
            prompt = (
                f"Competency: {competency}\n\nEvidence of under-performance:\n\n{evidence}\n\n"
                "Write the skill bullets for this competency."
            )
            return self.coach.complete(prompt, system=COACH_SYSTEM).strip()
        # Deterministic offline fallback: derive imperative advice from each check.
        return "\n".join(dict.fromkeys(_rule_advice(f) for f in failures))


def _collect_failures(case_results: list[CaseResult], competency: str) -> list[Failure]:
    failures: list[Failure] = []
    for cr in case_results:
        if cr.test_case.competency != competency:
            continue
        for res in cr.check_results:
            if res.score >= 1.0 or res.detail.startswith("SKIPPED"):
                continue
            failures.append(
                Failure(
                    case_id=cr.test_case.id,
                    competency=competency,
                    prompt=cr.test_case.prompt,
                    check_description=res.check.description,
                    check_type=res.check.type,
                    expected=_expected(res.check),
                    detail=res.detail,
                    response_excerpt=(cr.response or "(no answer)")[:300],
                )
            )
    return failures


def _expected(check: Check) -> str:
    if check.type == "llm_judge":
        return f"rubric: {check.rubric}"
    if check.type == "json_path_equals":
        return f"JSON field '{check.path}' == {check.value!r}"
    return f"{check.type}: {check.value!r}"


def _rule_advice(f: Failure) -> str:
    """Imperative, generalized advice composed from the check itself (offline path)."""
    t = f.check_type
    if t == "contains":
        return (f"When answering, explicitly state the key fact the task depends on "
                f"(here the answer had to mention {f.expected.split(': ', 1)[-1]}); "
                f"cite concrete policy values instead of vague reassurance.")
    if t == "not_contains":
        return ("Never produce the prohibited content this role forbids "
                f"(a check rejected: {f.detail}). When in doubt, decline and defer.")
    if t == "regex":
        return ("Give a direct, unambiguous verdict (approve/deny, can/cannot) rather "
                "than deflecting — graders look for an explicit decision.")
    if t in ("json_valid", "json_path_equals"):
        return ("When asked for JSON, return ONLY a JSON object, with exactly the "
                "requested keys — no prose, no missing fields "
                f"(failed: {f.detail}).")
    if t == "numeric_close":
        return "Compute the requested number explicitly and state it as a bare numeral."
    if t == "min_length":
        return "Give a substantive answer; one-liners fail this role's depth bar."
    if t == "max_length":
        return "Be concise; long answers fail this role's length bar."
    if t == "llm_judge":
        return f"Meet this rubric on every relevant task: {f.expected.removeprefix('rubric: ')}"
    return f"Fix: {f.detail}"


def _render_skill(candidate: str, guidance: list[CompetencyGuidance]) -> str:
    lines = [
        "SKILL: lessons from your most recent capability audit.",
        "Apply these on every task; they correct observed failures.",
        "",
    ]
    for g in guidance:
        lines.append(f"[{g.competency}]")
        for line in g.advice.splitlines():
            line = line.strip().lstrip("-• ")
            if line:
                lines.append(f"- {line}")
        lines.append("")
    return "\n".join(lines).strip()
