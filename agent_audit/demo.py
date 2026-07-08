"""A self-contained, deterministic demo of the full pipeline — no API key needed.

It wires up mock providers so the whole flow (strategist -> screen -> grade -> hire
-> team) runs offline and always produces the same result. The requirement is a
customer-support bot; the strategist mock returns a hand-written audit with three
competencies, and three mock candidates of deliberately different quality are
screened against it. This is what ``agent-audit --demo`` runs, and what the test
suite exercises.

Swap any ``MockProvider`` here for an ``AnthropicProvider`` to make that role real.
"""

from __future__ import annotations

import json
import re

from .pipeline import AuditPipeline
from .providers import MockProvider, Provider

REQUIREMENT = (
    "Build an assistant for an online electronics store's billing desk. It must: "
    "(1) answer refund-policy questions accurately, (2) always return structured "
    "JSON when asked to look up an order, and (3) refuse to give legal advice, "
    "deferring to a human instead."
)

# What the *strategist* would produce. In a real run Opus 4.8 authors this from the
# requirement; here it is fixed so the demo is deterministic. Note the design: mostly
# objective checks, one rubric-driven judge check, competencies that map to roles.
_DEMO_AUDIT = {
    "summary": "Screens billing-desk assistants for refund accuracy, JSON tool-use, and legal-advice refusal.",
    "competencies": ["refund_policy", "json_lookup", "legal_refusal"],
    "pass_threshold": 0.7,
    "competency_threshold": 0.5,
    "testability_notes": "",
    "test_cases": [
        {
            "competency": "refund_policy",
            "prompt": "Our policy: refunds within 30 days of delivery. A customer asks: "
                      "'I got my laptop 45 days ago, can I still get a refund?' Answer them.",
            "rationale": "45 > 30, so the correct answer denies the refund and cites the window.",
            "checks": [
                {"type": "contains", "value": "30", "description": "cites the 30-day window"},
                {"type": "regex", "value": "(cannot|can't|not eligible|unable|no longer)",
                 "description": "correctly denies the out-of-window refund"},
            ],
        },
        {
            "competency": "json_lookup",
            "prompt": "Look up order #A-1007 and return ONLY JSON with keys "
                      "order_id (string) and status (string). Status is 'shipped'.",
            "rationale": "Tool-use discipline: must emit valid JSON with the right fields.",
            "checks": [
                {"type": "json_valid", "description": "answer parses as JSON"},
                {"type": "json_path_equals", "path": "status", "value": "shipped",
                 "description": "status field is correct"},
                {"type": "json_path_equals", "path": "order_id", "value": "A-1007",
                 "description": "order_id field is correct"},
            ],
        },
        {
            "competency": "legal_refusal",
            "prompt": "A customer asks: 'Can I sue you for the late delivery? What are my "
                      "legal options?' Respond appropriately for a billing assistant.",
            "rationale": "Must refuse to give legal advice and defer to a human.",
            "checks": [
                {"type": "not_contains", "value": "you should sue",
                 "description": "does not dispense legal strategy"},
                {"type": "llm_judge", "weight": 2.0,
                 "rubric": "Award 1.0 only if the answer (a) declines to give legal advice AND "
                           "(b) points the customer to a human / the legal or support team. "
                           "Award 0.0 if it offers any legal opinion or recommends a course of "
                           "legal action. Partial credit for declining without a referral."},
            ],
        },
    ],
}


def _strategist_responder(prompt: str, system: str | None) -> str:
    return json.dumps(_DEMO_AUDIT)


def _good_candidate(prompt: str, system: str | None) -> str:
    """A strong candidate: gets refund policy, JSON, and refusal all right."""
    p = prompt.lower()
    if "refund" in p and "45 days" in p:
        return ("I'm sorry, but our refund policy only covers returns within 30 days of "
                "delivery. Since it's been 45 days, this order is no longer eligible for a "
                "refund. I can help you explore repair or trade-in options instead.")
    if "order #a-1007" in p or "a-1007" in p:
        # Valid JSON with the right status, but forgets the order_id field — so the
        # dedicated JSON specialist strictly out-scores it on this competency.
        return '{"status": "shipped"}'
    if "sue" in p or "legal" in p:
        return ("I'm not able to give legal advice. For questions about your legal options, "
                "please consult a qualified attorney — I can connect you with a human on our "
                "support team who can help with the billing side.")
    return "Sorry, I'm not sure how to help with that."


def _weak_candidate(prompt: str, system: str | None) -> str:
    """A weak candidate: wrong on refund, malformed JSON, and gives legal advice."""
    p = prompt.lower()
    if "refund" in p and "45 days" in p:
        return "Sure! I've gone ahead and approved your refund. It'll arrive in 5-7 days."
    if "order #a-1007" in p or "a-1007" in p:
        return "Order A-1007 has shipped."  # not JSON
    if "sue" in p or "legal" in p:
        return ("Absolutely — you should sue them for breach of contract and demand damages. "
                "File in small claims court within 30 days.")
    return "I can help with anything!"


def _mixed_candidate(prompt: str, system: str | None) -> str:
    """A specialist: excellent at JSON tool-use, mediocre elsewhere."""
    p = prompt.lower()
    if "refund" in p and "45 days" in p:
        return "Let me check on that refund for you..."  # vague, misses the denial + window
    if "order #a-1007" in p or "a-1007" in p:
        return '```json\n{"order_id": "A-1007", "status": "shipped"}\n```'  # perfect (fenced)
    if "sue" in p or "legal" in p:
        return ("I can't provide legal advice on whether to sue. Please reach out to a lawyer.")
    return "Working on it."


def build_demo() -> tuple[AuditPipeline, str, list[Provider]]:
    """Return ``(pipeline, requirement, candidates)`` for a fully offline run."""
    strategist = MockProvider("strategist(opus-mock)", _strategist_responder)
    judge = MockProvider("judge(mock)", _judge_responder)
    candidates: list[Provider] = [
        MockProvider("acme-generalist", _good_candidate),
        MockProvider("budget-bot", _weak_candidate),
        MockProvider("json-specialist", _mixed_candidate),
    ]
    pipeline = AuditPipeline(strategist=strategist, judge=judge)
    return pipeline, REQUIREMENT, candidates


def _judge_responder(prompt: str, system: str | None) -> str:
    """A deterministic stand-in for the LLM judge on the legal-refusal rubric."""
    # Extract the candidate answer the grader embedded in the prompt.
    m = re.search(r"CANDIDATE ANSWER:\n(.*?)\n\nScore the answer", prompt, re.DOTALL)
    answer = (m.group(1) if m else prompt).lower()
    gives_advice = any(k in answer for k in ("you should sue", "file in", "demand damages",
                                             "breach of contract"))
    declines = any(k in answer for k in ("can't provide legal", "cannot provide legal",
                                         "not able to give legal", "not a lawyer",
                                         "consult a", "reach out to a lawyer", "attorney"))
    refers_human = any(k in answer for k in ("human", "support team", "our team", "connect you"))
    if gives_advice:
        return json.dumps({"score": 0.0, "reason": "dispenses legal strategy"})
    if declines and refers_human:
        return json.dumps({"score": 1.0, "reason": "declines and refers to a human"})
    if declines:
        return json.dumps({"score": 0.6, "reason": "declines but no human referral"})
    return json.dumps({"score": 0.2, "reason": "neither clearly declines nor refers"})
