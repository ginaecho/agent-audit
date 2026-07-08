"""Tests for the discrimination loop (Stage 2)."""

from __future__ import annotations

from agent_audit.adaptive import adaptive_text_audit, design_discriminating
from agent_audit.pipeline import AuditPipeline
from agent_audit.providers import MockProvider


def test_loop_hardens_until_candidates_separate():
    # round 0 exam ties everyone; round 1+ (after hardening) separates them.
    def generate(round_index, feedback):
        return "hard" if round_index >= 1 else "easy"

    def screen(exam):
        if exam == "easy":
            return {"a": 1.0, "b": 1.0, "c": 1.0}   # no separation
        return {"a": 1.0, "b": 0.5, "c": 0.0}       # separated

    result = design_discriminating(generate, screen, max_rounds=3, min_discrimination=0.15)
    assert result.discriminating is True
    assert result.chosen_round == 1
    assert len(result.rounds) == 2                  # stopped as soon as it separated
    assert result.rounds[0].discrimination == 0.0
    assert result.rounds[1].discrimination == 1.0


def test_loop_returns_best_effort_when_never_separating():
    def generate(round_index, feedback):
        return round_index

    def screen(exam):
        # Slightly widening but never crossing the bar.
        return {"a": 1.0, "b": 1.0 - 0.03 * (exam + 1)}

    result = design_discriminating(generate, screen, max_rounds=3, min_discrimination=0.5)
    assert result.discriminating is False
    assert len(result.rounds) == 3
    # It keeps the most-discriminating round it saw (the last, widest here).
    assert result.chosen_round == 2


def test_harden_feedback_is_passed_to_the_strategist():
    # A mock strategist that returns a discriminating audit only once it has been
    # told to harden — proving the feedback reaches design_audit.
    import json

    def strategist(prompt, system=None):
        hardened = "FAILED TO DISCRIMINATE" in prompt
        checks = [{"type": "contains", "value": "hard" if hardened else "x"}]
        return json.dumps({
            "summary": "s", "competencies": ["c"],
            "test_cases": [{"competency": "c", "prompt": "p", "checks": checks}],
        })

    pipeline = AuditPipeline(strategist=MockProvider("strategist", strategist))
    # 'strong' says the hard keyword; 'weak' never does.
    strong = MockProvider("strong", lambda p, s: "this is hard")
    weak = MockProvider("weak", lambda p, s: "easy stuff")

    audit, result = adaptive_text_audit(
        pipeline, "req", [strong, weak], competencies=["c"],
        max_rounds=2, min_discrimination=0.15,
    )
    assert result.discriminating is True
    assert result.rounds[0].discrimination == 0.0   # round 0: both fail 'x' -> tie at 0
    assert result.chosen_round == 1                 # hardened round separates them
