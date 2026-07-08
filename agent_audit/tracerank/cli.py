"""CLI: rank agents from real usage traces, and emit per-agent improvement skills.

    python -m agent_audit.tracerank --demo                        # bundled Copilot sample
    python -m agent_audit.tracerank                                # your real VS Code Copilot chats
    python -m agent_audit.tracerank --source claude-code            # your real Claude Code sessions
    python -m agent_audit.tracerank --source claude-code --demo    # bundled Claude Code sample
    python -m agent_audit.tracerank --list-roots                   # show where it will look
    python -m agent_audit.tracerank --root /path/to/User

Runs entirely locally; trace contents never leave your machine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import claude_code as cc
from .adapters import copilot_vscode as cop
from .hints import hints_for_agent
from .leaderboard import build_leaderboard
from .signals import score_session

_DEMO_DIRS = {
    "copilot-vscode": Path(__file__).parent / "demo_traces",
    "claude-code": Path(__file__).parent / "demo_traces_claude_code",
}


def _load(args) -> list:
    if args.source == "claude-code":
        if args.demo:
            files = sorted(_DEMO_DIRS["claude-code"].rglob("subagents/*.jsonl"))
            return cc.load_sessions(files=files)
        roots = [Path(r) for r in args.root] if args.root else None
        return cc.load_sessions(roots, include_main_sessions=args.include_main_sessions)
    if args.demo:
        d = _DEMO_DIRS["copilot-vscode"]
        files = sorted(d.glob("*.json")) + sorted(d.glob("*.jsonl"))
        return cop.load_sessions(files=files)
    roots = [Path(r) for r in args.root] if args.root else None
    return cop.load_sessions(roots)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rank AI coding agents from usage traces.")
    ap.add_argument("--source", default="copilot-vscode", choices=["copilot-vscode", "claude-code"])
    ap.add_argument("--root", action="append", help="storage root to search (repeatable)")
    ap.add_argument("--demo", action="store_true", help="use bundled sample traces")
    ap.add_argument("--include-main-sessions", action="store_true",
                    help="claude-code only: also include whole top-level session "
                         "transcripts (coarser: one multi-task, possibly multi-model, "
                         "conversation counted as a single session)")
    ap.add_argument("--list-roots", action="store_true",
                    help="print discovered storage roots and exit")
    ap.add_argument("--min-hint-count", type=int, default=2)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    if args.list_roots:
        if args.source == "claude-code":
            roots = cc.default_project_roots()
            print("Discovered Claude Code roots:" if roots else "No Claude Code roots found.")
            for r in roots:
                n = len(cc.iter_subagent_files([r]))
                m = len(cc.iter_main_session_files([r]))
                print(f"  {r}   ({n} subagent session files, {m} main session files)")
        else:
            roots = cop.default_storage_roots()
            print("Discovered VS Code roots:" if roots else "No VS Code roots found.")
            for r in roots:
                n = len(cop.iter_session_files([r]))
                print(f"  {r}   ({n} chat-session files)")
        return 0

    sessions = _load(args)
    if not sessions:
        print("No sessions found. Try --demo, or pass --root <storage dir>. "
              "Run --list-roots to see where it looks.")
        return 1

    scores = [score_session(s) for s in sessions]
    lb = build_leaderboard(scores)
    agents = [r.agent for r in lb.rankings]
    hints = {a: hints_for_agent(scores, a, min_count=args.min_hint_count) for a in agents}

    if args.json:
        print(json.dumps({
            "global_mean": lb.global_mean,
            "task_kind_baselines": lb.task_kind_baselines,
            "rankings": [vars(r) for r in lb.rankings],
            "hints": {a: [vars(h) for h in hs] for a, hs in hints.items()},
        }, indent=2))
        return 0

    print(f"\nAgents ranked from {len(sessions)} sessions "
          f"(difficulty-adjusted; global success {lb.global_mean:.0%})\n")
    print(lb.table())
    print("\nImprovement skills (from recurring real-trace failures):")
    any_hint = False
    for a in agents:
        for h in hints[a]:
            any_hint = True
            print(f"\n  [{a}]  {h.diagnosis}  (seen {h.count}x)")
            print(f"    -> skill: {h.skill_text}")
    if not any_hint:
        print("  (no recurring failure patterns met the threshold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
