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
from .providers import (
    AnthropicProvider,
    FunctionProvider,
    MockProvider,
    Provider,
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
    "decide_hiring",
    "form_team",
    "__version__",
]
