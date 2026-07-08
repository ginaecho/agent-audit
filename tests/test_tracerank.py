"""Tests for trace-based ranking: signals, difficulty-adjusted leaderboard, hints."""

from __future__ import annotations

from pathlib import Path

from agent_audit.tracerank import (
    Session, Turn, Role, score_session, build_leaderboard, hints_for_agent,
)
from agent_audit.tracerank.adapters import copilot_vscode as cop
from agent_audit.tracerank.adapters import claude_code as cc

_DEMO = Path(__file__).resolve().parents[1] / "agent_audit" / "tracerank" / "demo_traces"
_CC_DEMO = (Path(__file__).resolve().parents[1] / "agent_audit" / "tracerank"
           / "demo_traces_claude_code" / "subagents")


def _s(sid, agent, turns, task_kind="", ended=True):
    return Session(session_id=sid, agent=agent, turns=turns, task_kind=task_kind,
                   source="test", ended_naturally=ended)


def test_hard_pass_and_thanks_scores_high():
    s = _s("1", "A", [
        Turn(Role.USER, "fix the failing test", tokens=10),
        Turn(Role.AGENT, "patched it", tokens=50),
        Turn(Role.TOOL, "pytest: all tests passed, exit code 0", tool_ok=True, tokens=20),
        Turn(Role.USER, "perfect, thanks!", tokens=5),
    ])
    sc = score_session(s)
    assert sc.outcome > 0.8 and sc.confidence > 0.4
    assert not sc.failure_tags


def test_force_stop_and_failure_scores_low():
    s = _s("2", "B", [
        Turn(Role.USER, "add feature X", tokens=10),
        Turn(Role.AGENT, "here", tokens=80),
        Turn(Role.TOOL, "build failed: compilation error", tool_ok=False, tokens=30),
        Turn(Role.USER, "no that's wrong, still broken, ugh", tokens=10),
    ], ended=False)
    sc = score_session(s)
    assert sc.outcome < 0.3
    assert "verifiable_failure_in_trace" in sc.failure_tags
    assert "session_force_stopped" in sc.failure_tags
    assert "user_frustration" in sc.failure_tags


def test_explicit_downvote_pulls_outcome_down():
    up = score_session(_s("u", "A", [Turn(Role.USER, "go"), Turn(Role.AGENT, "done", vote=1)]))
    down = score_session(_s("d", "A", [Turn(Role.USER, "go"), Turn(Role.AGENT, "done", vote=-1)]))
    assert up.outcome > down.outcome


def test_difficulty_adjustment_rewards_harder_tasks():
    # Agent HARD only does "hard" tasks (everyone struggles); agent EASY only does
    # "easy" tasks (everyone succeeds). Raw success favors EASY; after difficulty
    # adjustment HARD should not be unfairly buried.
    scores = []
    # baseline: on hard tasks, a reference agent gets ~0.4; on easy, ~0.95
    for i in range(4):
        scores.append(score_session(_s(f"ref-h{i}", "REF", [
            Turn(Role.USER, "hard thing"), Turn(Role.AGENT, "attempt"),
            Turn(Role.TOOL, "tests failed", tool_ok=False)], task_kind="hard")))
        scores.append(score_session(_s(f"ref-e{i}", "REF", [
            Turn(Role.USER, "easy thing"), Turn(Role.AGENT, "attempt"),
            Turn(Role.TOOL, "all tests passed", tool_ok=True),
            Turn(Role.USER, "thanks")], task_kind="easy")))
    # HARD agent: on hard tasks it actually SUCCEEDS (better than the hard baseline)
    for i in range(3):
        scores.append(score_session(_s(f"hard{i}", "HARD", [
            Turn(Role.USER, "hard thing"), Turn(Role.AGENT, "fix"),
            Turn(Role.TOOL, "all tests passed", tool_ok=True),
            Turn(Role.USER, "great")], task_kind="hard")))
    # EASY agent: on easy tasks it succeeds (same as everyone on easy)
    for i in range(3):
        scores.append(score_session(_s(f"easy{i}", "EASY", [
            Turn(Role.USER, "easy thing"), Turn(Role.AGENT, "fix"),
            Turn(Role.TOOL, "all tests passed", tool_ok=True),
            Turn(Role.USER, "ok")], task_kind="easy")))

    lb = build_leaderboard(scores)
    ranks = {r.agent: r for r in lb.rankings}
    # HARD beat the hard-task baseline; EASY only met the easy baseline -> HARD ranks above EASY
    assert ranks["HARD"].adjusted_success > ranks["EASY"].adjusted_success
    # and the leaderboard is sorted
    adj = [r.adjusted_success for r in lb.rankings]
    assert adj == sorted(adj, reverse=True)


def test_adapter_parses_flat_json():
    s = cop.parse_session_file(_DEMO / "alpha_debug.json")
    assert s is not None and s.agent == "gpt-4o" and s.source == "copilot-vscode"
    assert s.rounds == 2                                  # two user messages
    assert "off-by-one" in s.agent_turns[0].text
    assert s.task_kind == "debug"                         # inferred from "fix"/"test"
    assert s.ended_naturally is True


def test_adapter_parses_jsonl_base_plus_patches():
    s = cop.parse_session_file(_DEMO / "gamma_optimize.jsonl")
    assert s is not None and s.agent == "claude-sonnet-4.5"
    # the two turns were delivered as patch records onto an empty base 'requests'
    assert s.rounds == 2
    assert "composite index" in s.agent_turns[0].text
    assert score_session(s).outcome > 0.7                 # tests passed + "works great"


def test_adapter_detects_cancel_and_failure_signals():
    s = cop.parse_session_file(_DEMO / "beta_debug.json")
    sc = score_session(s)
    assert s.ended_naturally is False                     # last request canceled
    assert "verifiable_failure_in_trace" in sc.failure_tags
    assert sc.outcome < 0.4


def test_end_to_end_demo_ranks_and_hints():
    files = sorted(_DEMO.glob("*.json")) + sorted(_DEMO.glob("*.jsonl"))
    sessions = cop.load_sessions(files=files)
    assert len(sessions) == 6
    scores = [score_session(s) for s in sessions]
    lb = build_leaderboard(scores)
    # gpt-4o (clean passes) should outrank gpt-4o-mini (failures + cancels)
    order = [r.agent for r in lb.rankings]
    assert order.index("gpt-4o") < order.index("gpt-4o-mini")
    hints = hints_for_agent(scores, "gpt-4o-mini")
    assert any(h.tag == "verifiable_failure_in_trace" for h in hints)


def test_claude_code_adapter_parses_clean_pass():
    s = cc.parse_subagent_file(_CC_DEMO / "agent-clean-pass.jsonl")
    assert s is not None and s.agent == "claude-opus-4-8" and s.source == "claude-code"
    assert s.task_kind == "debug scheduler"           # leading "opus" stripped from description
    assert s.ended_naturally is True
    sc = score_session(s)
    assert sc.outcome > 0.8                           # tool_result "all tests passed" is now
                                                       # surfaced as a hard-pass TOOL turn


def test_claude_code_adapter_surfaces_successful_tool_results():
    # Regression: earlier the adapter only emitted a Turn for is_error=True tool
    # results, silently dropping successful ones -- discarding exactly the "hard
    # pass" evidence (e.g. "all tests passed") the scorer looks for.
    s = cc.parse_subagent_file(_CC_DEMO / "agent-clean-pass.jsonl")
    tool_turns = [t for t in s.turns if t.role is Role.TOOL]
    assert len(tool_turns) == 1 and tool_turns[0].tool_ok is True
    assert "all tests passed" in tool_turns[0].text


def test_claude_code_adapter_detects_failure_and_stop_hook_block():
    s = cc.parse_subagent_file(_CC_DEMO / "agent-tool-fail.jsonl")
    assert s.agent == "claude-haiku-4-5-20251001"
    sc = score_session(s)
    assert "verifiable_failure_in_trace" in sc.failure_tags
    assert sc.outcome < 0.3
    # the stop_hook_summary record (preventedContinuation=true) becomes a second,
    # distinct hard-negative TOOL turn -- a Claude-Code-specific signal grounded in
    # a real field (a Stop hook judged the "done" claim premature).
    tool_texts = " ".join(t.text for t in s.turns if t.role is Role.TOOL)
    assert "stop_hook_blocked" in tool_texts


def test_claude_code_demo_ranks_clean_above_failing():
    files = sorted(_CC_DEMO.glob("*.jsonl"))
    sessions = cc.load_sessions(files=files)
    assert len(sessions) == 3
    scores = [score_session(s) for s in sessions]
    lb = build_leaderboard(scores)
    order = {r.agent: r.adjusted_success for r in lb.rankings}
    assert order["claude-opus-4-8"] > order["claude-haiku-4-5-20251001"]
    assert order["claude-sonnet-5"] > order["claude-haiku-4-5-20251001"]


def test_hints_fire_on_repeated_failures():
    scores = []
    for i in range(3):
        scores.append(score_session(_s(f"f{i}", "B", [
            Turn(Role.USER, "do it"), Turn(Role.AGENT, "k"),
            Turn(Role.TOOL, "tests failed", tool_ok=False),
            Turn(Role.USER, "still broken")], task_kind="code")))
    hints = hints_for_agent(scores, "B")
    tags = {h.tag for h in hints}
    assert "verifiable_failure_in_trace" in tags
    assert all(h.skill_text for h in hints)
