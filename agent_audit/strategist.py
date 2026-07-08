"""The strategist: the most powerful agent, which authors the audit.

Given a natural-language requirement (user intent), the strategist writes a
bespoke exam — competencies, test cases, and per-case checks — that a candidate
must pass to be hired. Design constraints baked into the prompt come straight from
the prior-art scan (docs/RESEARCH.md):

* prefer **objective, deterministic checks**; reserve the LLM judge for genuinely
  open-ended criteria (RESEARCH §1, §2);
* make the exam **discriminative** — spread difficulty so it actually separates
  strong from weak candidates, rather than rubber-stamping everyone (§1);
* organise items by **competency** so hiring produces a per-role profile (§4);
* **flag untestable requirements** instead of fabricating a low-fidelity exam.

The strategist is deliberately a *different* role from the grader/judge to blunt
self-preference bias (§2).
"""

from __future__ import annotations

import json
import re
import uuid

from .models import AuditSpec, Check, TestCase
from .providers import Provider

_VALID_CHECK_TYPES = {
    "contains", "not_contains", "regex", "equals", "json_valid",
    "json_path_equals", "numeric_close", "min_length", "max_length", "llm_judge",
}

SYSTEM_PROMPT = """\
You are the Strategist in an agent-hiring pipeline. You are the most capable model \
in the system. Your job: read a system requirement (the user's intent) and design \
an AUDIT — a bespoke exam — that will be run against candidate LLMs and agents to \
decide which ones are competent enough to be HIRED for this requirement.

You do NOT answer the requirement yourself. You design the test that separates \
candidates who can do the job from those who cannot.

Principles you must follow:
1. Decompose the requirement into 2-5 named COMPETENCIES (distinct skills the job \
   needs, e.g. "sql_generation", "refusal_safety", "json_formatting").
2. Write concrete TEST CASES, each tagged with one competency. Spread difficulty \
   (easy / medium / hard) so the exam DISCRIMINATES — a good exam is failed by weak \
   candidates and passed by strong ones. Cover each competency with >= 1 case.
3. For each test case, write CHECKS that grade the answer. STRONGLY PREFER objective, \
   deterministic checks with a known-correct answer over the LLM judge. Use the judge \
   only for genuinely open-ended quality that no deterministic check can capture.
4. If part of the requirement cannot be reduced to a fair, automatically-gradable \
   test, say so in "testability_notes" rather than inventing a weak proxy.

Available check types and their fields:
- "contains" {value}: answer must contain the substring value.
- "not_contains" {value}: answer must NOT contain the substring value.
- "regex" {value}: answer must match the regex value.
- "equals" {value}: answer, trimmed, must equal value.
- "min_length" {value}: answer length >= value characters.
- "max_length" {value}: answer length <= value characters.
- "json_valid" {}: answer (or its fenced code block) must parse as JSON.
- "json_path_equals" {path, value}: JSON at dotted path equals value, e.g. path "status".
- "numeric_close" {value, tolerance}: first number in the answer is within tolerance of value.
- "llm_judge" {rubric}: a separate judge model scores the answer against the rubric \
  (0..1). Write the rubric as explicit, itemized criteria — never "is this good?".

Every check may set "weight" (default 1.0) and "description".

Return ONLY a JSON object (no prose, no markdown fence) with this exact shape:
{
  "summary": "one sentence on what this audit screens for",
  "competencies": ["comp_a", "comp_b"],
  "pass_threshold": 0.7,
  "competency_threshold": 0.5,
  "testability_notes": "anything in the requirement that resists fair auto-grading, or ''",
  "test_cases": [
    {
      "competency": "comp_a",
      "prompt": "the exact prompt to send each candidate",
      "weight": 1.0,
      "rationale": "why this item and what it separates",
      "checks": [
        {"type": "contains", "value": "...", "weight": 1.0, "description": "..."}
      ]
    }
  ]
}
"""


class Strategist:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    def design_audit(
        self,
        requirement: str,
        *,
        version: int = 1,
        competencies: list[str] | None = None,
        harden_feedback: str | None = None,
    ) -> AuditSpec:
        """Author an audit. Pass ``competencies`` to pin the role vocabulary —
        needed when downstream work (e.g. the harness's job tasks) is already
        tagged with specific competency names the team must be staffed under.

        Pass ``harden_feedback`` (from the adaptive loop) when a previous exam
        failed to separate candidates; the strategist is told to make the items
        substantially harder and more discriminating."""
        constraint = ""
        if competencies:
            names = ", ".join(f'"{c}"' for c in competencies)
            constraint = (
                f"\n\nUse EXACTLY these competency names (cover each with >=1 test "
                f"case, add no others): [{names}]"
            )
        harden = ""
        if harden_feedback:
            harden = (
                "\n\nThe previous version of this audit FAILED TO DISCRIMINATE the "
                "candidates (their scores were too close to make a hiring decision). "
                "Make this version substantially harder and more separating: add edge "
                "cases, adversarial inputs, multi-step reasoning, and tighter checks "
                "that a weaker candidate will get wrong but a stronger one will pass. "
                f"Details:\n{harden_feedback}"
            )
        user_prompt = (
            "Design an audit for the following system requirement.\n\n"
            f"REQUIREMENT:\n{requirement.strip()}{constraint}{harden}\n\n"
            "Return only the JSON object described in your instructions."
        )
        raw = self.provider.complete(user_prompt, system=SYSTEM_PROMPT)
        data = _extract_json(raw)
        return _build_audit(requirement, data, version=version)


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response, tolerating code fences/prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError(f"Strategist did not return parseable JSON. Got:\n{text[:500]}")


def _build_audit(requirement: str, data: dict, *, version: int) -> AuditSpec:
    competencies = list(data.get("competencies") or [])
    cases: list[TestCase] = []
    for i, raw_case in enumerate(data.get("test_cases") or []):
        checks: list[Check] = []
        for raw_check in raw_case.get("checks") or []:
            ctype = raw_check.get("type")
            if ctype not in _VALID_CHECK_TYPES:
                # Skip unknown check types rather than crash the whole audit.
                continue
            checks.append(
                Check(
                    type=ctype,
                    description=raw_check.get("description", ""),
                    weight=float(raw_check.get("weight", 1.0)),
                    value=raw_check.get("value"),
                    path=raw_check.get("path", ""),
                    tolerance=float(raw_check.get("tolerance", 1e-6)),
                    case_sensitive=bool(raw_check.get("case_sensitive", False)),
                    rubric=raw_check.get("rubric", ""),
                )
            )
        if not checks:
            continue
        competency = raw_case.get("competency") or (competencies[0] if competencies else "general")
        if competency not in competencies:
            competencies.append(competency)
        cases.append(
            TestCase(
                id=raw_case.get("id") or f"tc_{i+1}_{uuid.uuid4().hex[:6]}",
                competency=competency,
                prompt=raw_case["prompt"],
                checks=checks,
                weight=float(raw_case.get("weight", 1.0)),
                rationale=raw_case.get("rationale", ""),
            )
        )
    if not cases:
        raise ValueError("Strategist produced an audit with no gradable test cases.")
    return AuditSpec(
        requirement=requirement,
        summary=data.get("summary", ""),
        competencies=competencies,
        test_cases=cases,
        pass_threshold=float(data.get("pass_threshold", 0.7)),
        competency_threshold=float(data.get("competency_threshold", 0.5)),
        testability_notes=data.get("testability_notes", ""),
        version=version,
    )
