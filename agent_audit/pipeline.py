"""End-to-end orchestration: requirement -> audit -> screen -> hire -> team.

``AuditPipeline`` wires the strategist, runner, grader and hiring logic together and
returns an ``AuditRun`` — a single serializable artifact holding the generated exam,
every candidate transcript, the hiring decisions, and the final team. That artifact
is the auditable record governance frameworks ask for (docs/RESEARCH.md §6).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .grader import Grader
from .hiring import decide_hiring, form_team
from .models import AuditSpec, CandidateReport, Team
from .providers import Provider
from .runner import Runner
from .strategist import Strategist


@dataclass
class AuditRun:
    requirement: str
    audit: AuditSpec
    reports: list[CandidateReport]
    team: Team
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """A compact human-readable digest of the run."""
        lines = [
            f"Requirement: {self.requirement}",
            f"Audit: {self.audit.summary}",
            f"  competencies: {', '.join(self.audit.competencies)}",
            f"  test cases: {len(self.audit.test_cases)}  "
            f"pass>={self.audit.pass_threshold:.2f}  "
            f"per-competency>={self.audit.competency_threshold:.2f}",
        ]
        if self.audit.testability_notes:
            lines.append(f"  ⚠ testability: {self.audit.testability_notes}")
        lines.append("")
        lines.append("Candidates (by overall score):")
        for r in sorted(self.reports, key=lambda r: r.overall_score, reverse=True):
            mark = "✅" if r.hired else "❌"
            comp = "  ".join(f"{k}:{v:.2f}" for k, v in r.competency_scores.items())
            lines.append(f"  {mark} {r.candidate:<22} {r.overall_score:.2f}   [{comp}]")
        lines.append("")
        lines.append(f"Team lead: {self.team.lead or '(none — no candidate hired)'}")
        for a in self.team.assignments:
            who = a.candidate or "— UNSTAFFED —"
            lines.append(f"  role {a.competency:<20} -> {who}  ({a.score:.2f})")
        if self.team.unstaffed:
            lines.append(f"  ⚠ unstaffed roles: {', '.join(self.team.unstaffed)}")
        return "\n".join(lines)


class AuditPipeline:
    def __init__(
        self,
        strategist: Provider,
        judge: Provider | None = None,
    ) -> None:
        self.strategist = Strategist(strategist)
        self.grader = Grader(judge=judge)
        self.runner = Runner(self.grader)

    def run(
        self,
        requirement: str,
        candidates: list[Provider],
        *,
        audit: AuditSpec | None = None,
        competencies: list[str] | None = None,
    ) -> AuditRun:
        """Screen ``candidates`` against ``requirement`` and hire a team.

        Pass a pre-built ``audit`` to re-run an existing exam (re-certification)
        instead of authoring a fresh one, or ``competencies`` to pin the role
        vocabulary the strategist must use (see ``Strategist.design_audit``).
        """
        if audit is None:
            audit = self.strategist.design_audit(requirement, competencies=competencies)
        reports = [self.runner.run(audit, candidate) for candidate in candidates]
        decide_hiring(audit, reports)
        team = form_team(audit, reports)
        return AuditRun(requirement=requirement, audit=audit, reports=reports, team=team)
