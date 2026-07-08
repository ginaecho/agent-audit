"""Grading: turn a candidate's answer into per-check, per-case scores.

Objective checks are deterministic. The one non-deterministic check, ``llm_judge``,
is delegated to a *separate* judge provider — different role, ideally different model
family than both the strategist and the candidates — because a model that authors or
resembles the thing it grades exhibits self-preference bias (docs/RESEARCH.md §2).
If no judge is configured, ``llm_judge`` checks are skipped and excluded from the
score (with a note), so the engine degrades gracefully offline.
"""

from __future__ import annotations

import json
import re

from .models import CaseResult, Check, CheckResult, TestCase
from .providers import Provider

JUDGE_SYSTEM = """\
You are an impartial Grader in an agent-hiring pipeline. You score a candidate's \
answer against an explicit rubric. You did not write the exam and you are not a \
candidate. Judge only what the rubric asks. Ignore answer length and surface style \
unless the rubric mentions them. Do not reward an answer for resembling how you \
would have written it.

Respond with ONLY a JSON object: {"score": <float 0..1>, "reason": "<one sentence>"}.\
"""


class Grader:
    def __init__(self, judge: Provider | None = None) -> None:
        self.judge = judge

    def grade_case(self, test_case: TestCase, response: str, *, latency_s: float = 0.0,
                   error: str = "") -> CaseResult:
        if error:
            results = [
                CheckResult(check=c, passed=False, score=0.0, detail=f"candidate error: {error}")
                for c in test_case.checks
            ]
            return CaseResult(test_case, response, results, 0.0, latency_s, error)

        results: list[CheckResult] = []
        for check in test_case.checks:
            results.append(self._grade_check(check, response, test_case))

        scored = [(r, r.check.weight) for r in results if not _is_skipped(r)]
        total_w = sum(w for _, w in scored)
        score = sum(r.score * w for r, w in scored) / total_w if total_w else 0.0
        return CaseResult(test_case, response, results, score, latency_s)

    def _grade_check(self, check: Check, response: str, test_case: TestCase) -> CheckResult:
        try:
            if check.type == "llm_judge":
                return self._grade_llm(check, response, test_case)
            handler = _OBJECTIVE[check.type]
        except KeyError:
            return CheckResult(check, False, 0.0, f"unknown check type '{check.type}'")
        passed, detail = handler(check, response)
        return CheckResult(check, passed, 1.0 if passed else 0.0, detail)

    def _grade_llm(self, check: Check, response: str, test_case: TestCase) -> CheckResult:
        if self.judge is None:
            return CheckResult(check, False, 0.0, "SKIPPED: no judge provider configured")
        prompt = (
            f"RUBRIC:\n{check.rubric}\n\n"
            f"ORIGINAL PROMPT GIVEN TO THE CANDIDATE:\n{test_case.prompt}\n\n"
            f"CANDIDATE ANSWER:\n{response}\n\n"
            "Score the answer against the rubric."
        )
        raw = self.judge.complete(prompt, system=JUDGE_SYSTEM)
        score, reason = _parse_judge(raw)
        return CheckResult(check, score >= 0.5, score, f"judge: {reason}")


# --- Deterministic check handlers -------------------------------------------
# Each returns (passed: bool, detail: str).


def _norm(s: str, case_sensitive: bool) -> str:
    return s if case_sensitive else s.lower()


def _check_contains(check: Check, response: str):
    needle = str(check.value)
    ok = _norm(needle, check.case_sensitive) in _norm(response, check.case_sensitive)
    return ok, f"{'found' if ok else 'missing'} substring {needle!r}"


def _check_not_contains(check: Check, response: str):
    needle = str(check.value)
    ok = _norm(needle, check.case_sensitive) not in _norm(response, check.case_sensitive)
    return ok, f"substring {needle!r} {'absent' if ok else 'present'}"


def _check_regex(check: Check, response: str):
    flags = 0 if check.case_sensitive else re.IGNORECASE
    ok = re.search(str(check.value), response, flags) is not None
    return ok, f"regex {check.value!r} {'matched' if ok else 'no match'}"


def _check_equals(check: Check, response: str):
    a, b = response.strip(), str(check.value).strip()
    ok = a == b if check.case_sensitive else a.lower() == b.lower()
    return ok, "exact match" if ok else f"expected {b!r}, got {a[:60]!r}"


def _check_min_length(check: Check, response: str):
    ok = len(response) >= int(check.value)
    return ok, f"length {len(response)} (min {check.value})"


def _check_max_length(check: Check, response: str):
    ok = len(response) <= int(check.value)
    return ok, f"length {len(response)} (max {check.value})"


def _extract_json_blob(response: str):
    text = response.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _check_json_valid(check: Check, response: str):
    ok = _extract_json_blob(response) is not None
    return ok, "valid JSON" if ok else "not valid JSON"


def _check_json_path_equals(check: Check, response: str):
    blob = _extract_json_blob(response)
    if blob is None:
        return False, "no JSON to inspect"
    node = blob
    for part in [p for p in check.path.split(".") if p]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False, f"path '{check.path}' not found"
    ok = node == check.value
    return ok, f"path '{check.path}' = {node!r} (expected {check.value!r})"


def _check_numeric_close(check: Check, response: str):
    m = re.search(r"-?\d+(?:\.\d+)?", response.replace(",", ""))
    if not m:
        return False, "no number found in answer"
    got = float(m.group())
    ok = abs(got - float(check.value)) <= check.tolerance
    return ok, f"got {got} (target {check.value} ± {check.tolerance})"


_OBJECTIVE = {
    "contains": _check_contains,
    "not_contains": _check_not_contains,
    "regex": _check_regex,
    "equals": _check_equals,
    "min_length": _check_min_length,
    "max_length": _check_max_length,
    "json_valid": _check_json_valid,
    "json_path_equals": _check_json_path_equals,
    "numeric_close": _check_numeric_close,
}


def _is_skipped(result: CheckResult) -> bool:
    return result.detail.startswith("SKIPPED")


def _parse_judge(raw: str):
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start : end + 1]) if start != -1 and end > start else {}
    score = float(data.get("score", 0.0))
    score = max(0.0, min(1.0, score))
    return score, str(data.get("reason", ""))
