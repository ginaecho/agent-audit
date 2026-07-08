"""Tests for efficiency-weighted scoring and discrimination metrics."""

from __future__ import annotations

from agent_audit.scoring import (
    Attempt,
    Effort,
    discrimination_index,
    efficiency_leaderboard,
    efficiency_score,
    is_discriminating,
    rank_task,
)


def test_cheapest_correct_wins_the_task():
    attempts = [
        Attempt("opus", 1.0, Effort(usd=0.55)),
        Attempt("sonnet", 1.0, Effort(usd=0.41)),
        Attempt("haiku", 1.0, Effort(usd=0.10)),
    ]
    scores = rank_task(attempts)
    assert scores["haiku"] == 1.0                 # cheapest correct answer
    assert scores["sonnet"] < scores["haiku"]
    assert scores["opus"] < scores["sonnet"]      # priciest correct answer scores lowest


def test_wrong_but_cheap_scores_zero():
    # Being cheap is worthless if you're wrong.
    assert efficiency_score(correctness=0.5, cost=1.0, cost_min=1.0,
                            correctness_bar=1.0) == 0.0
    attempts = [
        Attempt("cheap_wrong", 0.0, Effort(usd=0.01)),
        Attempt("pricey_right", 1.0, Effort(usd=1.00)),
    ]
    scores = rank_task(attempts)
    assert scores["cheap_wrong"] == 0.0
    assert scores["pricey_right"] == 1.0          # only correct candidate -> full marks


def test_efficiency_discriminates_where_correctness_ties():
    # The run-1 situation: everyone correct, correctness gives no signal.
    correctness = [1.0, 1.0, 1.0]
    assert discrimination_index(correctness) == 0.0
    assert not is_discriminating(correctness)

    attempts = [
        Attempt("opus", 1.0, Effort(usd=0.55)),
        Attempt("sonnet", 1.0, Effort(usd=0.41)),
        Attempt("haiku", 1.0, Effort(usd=0.10)),
    ]
    eff = efficiency_leaderboard([attempts])
    assert is_discriminating(list(eff.values()))
    assert max(eff, key=eff.get) == "haiku"


def test_path_length_weights_for_agentic_tasks():
    # Same tokens, but one agent solved it in fewer tool calls -> it wins.
    attempts = [
        Attempt("planner", 1.0, Effort(tokens=1000, tool_calls=2)),
        Attempt("flailer", 1.0, Effort(tokens=1000, tool_calls=9)),
    ]
    scores = rank_task(attempts, weights={"tokens": 1.0, "tool_calls": 500.0})
    assert scores["planner"] == 1.0
    assert scores["flailer"] < 1.0
