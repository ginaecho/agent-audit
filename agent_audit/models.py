"""Core data model for the audit-driven hiring pipeline.

Everything here is a plain dataclass so an entire run — the generated audit, every
candidate transcript, and the hiring rationale — serializes to JSON and becomes a
first-class, versioned artifact (see ``docs/RESEARCH.md`` §6, governance).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CheckType = Literal[
    "contains",
    "not_contains",
    "regex",
    "equals",
    "json_valid",
    "json_path_equals",
    "numeric_close",
    "min_length",
    "max_length",
    "llm_judge",
]


@dataclass
class Check:
    """A single gradeable assertion against a candidate's answer.

    Objective checks (everything except ``llm_judge``) are deterministic and carry
    the score wherever possible; ``llm_judge`` is reserved for open-ended criteria
    and is always driven by an explicit ``rubric`` — the research is clear that a
    bare "is this good?" judge is biased and unreliable (docs/RESEARCH.md §2).
    """

    type: CheckType
    description: str = ""
    weight: float = 1.0
    # Objective-check parameters (interpretation depends on ``type``):
    value: Any = None          # expected substring / pattern / literal / number / length
    path: str = ""             # dotted path for json_path_equals, e.g. "user.name"
    tolerance: float = 1e-6     # for numeric_close
    case_sensitive: bool = False
    # llm_judge parameter:
    rubric: str = ""           # what the judge should reward / penalize, explicitly


@dataclass
class TestCase:
    """One exam question: a prompt plus the checks its answer must satisfy."""

    __test__ = False  # tell pytest this dataclass is not a test class to collect

    id: str
    competency: str
    prompt: str
    checks: list[Check]
    weight: float = 1.0
    rationale: str = ""        # why the strategist included this item


@dataclass
class AuditSpec:
    """The exam authored by the strategist from a single requirement."""

    requirement: str
    summary: str
    competencies: list[str]
    test_cases: list[TestCase]
    pass_threshold: float = 0.7   # min overall weighted score (0..1) to be hired
    competency_threshold: float = 0.5  # min per-competency score to staff that role
    testability_notes: str = ""   # strategist flags anything not cleanly gradable
    version: int = 1
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Grading / results -------------------------------------------------------


@dataclass
class CheckResult:
    check: Check
    passed: bool
    score: float          # 0..1
    detail: str = ""


@dataclass
class CaseResult:
    test_case: TestCase
    response: str
    check_results: list[CheckResult]
    score: float          # weighted mean of check scores, 0..1
    latency_s: float = 0.0
    error: str = ""       # populated if the candidate raised while answering


@dataclass
class CandidateReport:
    """Everything the audit learned about one candidate."""

    candidate: str
    overall_score: float
    competency_scores: dict[str, float]
    case_results: list[CaseResult]
    hired: bool = False
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Team --------------------------------------------------------------------


@dataclass
class RoleAssignment:
    competency: str
    candidate: str | None   # None => no candidate cleared the bar for this role
    score: float
    reason: str = ""


@dataclass
class Team:
    requirement: str
    lead: str | None                 # best overall hired candidate, the coordinator
    hired: list[str]
    assignments: list[RoleAssignment]
    unstaffed: list[str] = field(default_factory=list)  # competencies nobody cleared

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
