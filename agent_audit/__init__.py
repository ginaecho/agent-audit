"""agent-audit: audit-driven screening to hire and team up AI agents.

A strategist LLM turns a system requirement into a bespoke audit (an exam), runs it
against candidate LLMs / agents, hires the ones that pass, and assembles them into a
team — with the whole run captured as an auditable, versioned artifact.

Quick start (offline, no API key needed)::

    from agent_audit import AuditPipeline
    from agent_audit.providers import MockProvider

    pipeline = AuditPipeline(strategist=MockProvider("strategist", my_audit_json))
    run = pipeline.run(requirement, candidates=[cand_a, cand_b])
    print(run.summary())

Screen real Claude models by swapping in ``AnthropicProvider`` (install the
``anthropic`` extra). See ``examples/`` and ``docs/RESEARCH.md``.
"""

from .adaptive import AdaptiveResult, adaptive_text_audit, design_discriminating
from .agentic_harness import AgenticCase, AgenticHarness
from .coach import Coach, CompetencyGuidance, ImprovementPlan
from .execution import (
    CodingAudit,
    CodingTask,
    build_coding_audit,
    run_code,
    run_coding_audit,
    solve_coding_task,
)
from .sandbox import run_code_sandboxed
from .harness import Harness, HarnessReport, JobTask, RequirementCase
from .hiring import decide_hiring, form_team
from .models import (
    AuditSpec,
    CandidateReport,
    CaseResult,
    Check,
    CheckResult,
    RoleAssignment,
    Team,
    TestCase,
)
from .pipeline import AuditPipeline, AuditRun
from .scoring import (
    Attempt,
    Effort,
    discrimination_index,
    efficiency_leaderboard,
    efficiency_score,
    is_discriminating,
    rank_task,
)
from .providers import (
    CANDIDATE_MODELS,
    JUDGE_MODEL,
    STRATEGIST_MODEL,
    AnthropicProvider,
    FunctionProvider,
    MockProvider,
    Provider,
    SkilledProvider,
)
from .strategist import Strategist

__version__ = "0.1.0"

__all__ = [
    "AuditPipeline",
    "AuditRun",
    "Strategist",
    "AuditSpec",
    "TestCase",
    "Check",
    "CheckResult",
    "CaseResult",
    "CandidateReport",
    "RoleAssignment",
    "Team",
    "Provider",
    "MockProvider",
    "FunctionProvider",
    "AnthropicProvider",
    "SkilledProvider",
    "Coach",
    "ImprovementPlan",
    "CompetencyGuidance",
    "Harness",
    "HarnessReport",
    "JobTask",
    "RequirementCase",
    "AgenticHarness",
    "AgenticCase",
    "STRATEGIST_MODEL",
    "JUDGE_MODEL",
    "CANDIDATE_MODELS",
    "Attempt",
    "Effort",
    "efficiency_score",
    "rank_task",
    "efficiency_leaderboard",
    "discrimination_index",
    "is_discriminating",
    "design_discriminating",
    "adaptive_text_audit",
    "AdaptiveResult",
    "CodingTask",
    "CodingAudit",
    "build_coding_audit",
    "solve_coding_task",
    "run_coding_audit",
    "run_code",
    "run_code_sandboxed",
    "decide_hiring",
    "form_team",
    "__version__",
]
