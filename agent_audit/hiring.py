"""Hiring and team formation — the step no existing tool performs (RESEARCH §3-4).

Two distinct decisions, both scored on a per-competency profile rather than a single
scalar (echoing DyLAN's importance-score selection and MetaGPT's role staffing):

* **Overall hire** — a candidate that clears the overall ``pass_threshold`` is a
  qualified generalist and is eligible to be the team *lead* / coordinator.
* **Specialist hire** — team roles are staffed by whichever candidate scores best on
  that competency and clears its ``competency_threshold``, *even if it failed the
  overall bar*. This is the point of "group agents": a narrow specialist gets hired
  onto the team for the one role it excels at, alongside a generalist lead.
"""

from __future__ import annotations

from .models import AuditSpec, CandidateReport, RoleAssignment, Team


def decide_hiring(audit: AuditSpec, reports: list[CandidateReport]) -> list[CandidateReport]:
    """Mark each report ``hired`` and attach a rationale (mutates and returns them)."""
    for report in reports:
        hired = report.overall_score >= audit.pass_threshold
        report.hired = hired
        strengths = sorted(
            report.competency_scores.items(), key=lambda kv: kv[1], reverse=True
        )
        top = ", ".join(f"{k}={v:.2f}" for k, v in strengths[:3])
        verb = "HIRED" if hired else "not hired"
        report.rationale = (
            f"{verb}: overall {report.overall_score:.2f} vs threshold "
            f"{audit.pass_threshold:.2f}. Competencies: {top}."
        )
    return reports


def form_team(
    audit: AuditSpec,
    reports: list[CandidateReport],
    *,
    cost: dict[str, float] | None = None,
    tie_tolerance: float = 1e-9,
) -> Team:
    """Assemble a team: one best-fit candidate per competency, plus a generalist lead.

    Any candidate clearing a competency's bar is eligible to staff that role
    (specialist hiring); overall-hire status is required only to be the lead.

    ``cost`` maps candidate name -> a relative cost (e.g. output $/Mtok). When two
    candidates tie on a competency within ``tie_tolerance``, the cheaper one is
    hired — so an audit that fails to separate strong from weak candidates still
    pays off by certifying that the *cheapest sufficient* model can do the job
    (the FrugalGPT-style win). Without ``cost``, ties fall to the first top scorer.
    """
    generalists = [r for r in reports if r.hired]
    assignments: list[RoleAssignment] = []
    unstaffed: list[str] = []

    def _pick(pool: list[CandidateReport], key) -> CandidateReport:
        top = max(key(r) for r in pool)
        tied = [r for r in pool if key(r) >= top - tie_tolerance]
        if cost is not None and len(tied) > 1:
            return min(tied, key=lambda r: cost.get(r.candidate, float("inf")))
        return tied[0]

    for competency in audit.competencies:
        eligible = [
            r for r in reports
            if r.competency_scores.get(competency, 0.0) >= audit.competency_threshold
        ]
        if not eligible:
            assignments.append(
                RoleAssignment(
                    competency=competency,
                    candidate=None,
                    score=0.0,
                    reason=(
                        f"no candidate cleared the competency bar "
                        f"({audit.competency_threshold:.2f})"
                    ),
                )
            )
            unstaffed.append(competency)
            continue
        best = _pick(eligible, lambda r: r.competency_scores.get(competency, 0.0))
        role_score = best.competency_scores.get(competency, 0.0)
        tier = "generalist hire" if best.hired else "specialist hire (below overall bar)"
        cheap = cost is not None and len([
            r for r in eligible
            if r.competency_scores.get(competency, 0.0) >= role_score - tie_tolerance
        ]) > 1
        note = f"{tier}, cheapest of the passers" if cheap else tier
        assignments.append(
            RoleAssignment(
                competency=competency,
                candidate=best.candidate,
                score=role_score,
                reason=f"competency score {role_score:.2f} — {note}",
            )
        )

    lead = _pick(generalists, lambda r: r.overall_score).candidate if generalists else None
    # The team roster is everyone actually contributing: generalist lead(s) + any
    # specialists staffed into a role.
    staffed = {a.candidate for a in assignments if a.candidate}
    roster = {r.candidate for r in generalists} | staffed
    ranked_roster = [
        r.candidate for r in sorted(reports, key=lambda r: r.overall_score, reverse=True)
        if r.candidate in roster
    ]
    return Team(
        requirement=audit.requirement,
        lead=lead,
        hired=ranked_roster,
        assignments=assignments,
        unstaffed=unstaffed,
    )
