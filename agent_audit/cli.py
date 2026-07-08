"""Command-line entry point.

Examples
--------
Offline demo (no API key, deterministic)::

    agent-audit --demo

Screen real Claude models against a requirement::

    agent-audit "Build a bot that answers billing questions and never gives legal advice" \\
        --candidates claude-haiku-4-5 claude-sonnet-5 claude-opus-4-8 \\
        --out runs/billing.audit.json
"""

from __future__ import annotations

import argparse
import json
import sys

from .pipeline import AuditPipeline, AuditRun
from .providers import (
    JUDGE_MODEL,
    STRATEGIST_MODEL,
    AnthropicProvider,
    MockProvider,
    Provider,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-audit",
        description="Audit-driven screening to hire and team up AI agents.",
    )
    parser.add_argument("requirement", nargs="?", help="the system requirement / user intent")
    parser.add_argument(
        "--candidates", nargs="+", default=[],
        help="candidate Claude model IDs to screen (e.g. claude-haiku-4-5 claude-sonnet-5)",
    )
    parser.add_argument("--strategist", default=STRATEGIST_MODEL, help="strategist model ID")
    parser.add_argument("--judge", default=JUDGE_MODEL, help="judge model ID for llm_judge checks")
    parser.add_argument("--out", help="write the full run artifact as JSON to this path")
    parser.add_argument("--demo", action="store_true", help="run the offline demo (no API key)")
    args = parser.parse_args(argv)

    if args.demo:
        run = _demo_run()
    else:
        if not args.requirement:
            parser.error("provide a requirement, or use --demo")
        if not args.candidates:
            parser.error("provide at least one --candidates model id")
        run = _real_run(args)

    print(run.summary())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(run.to_dict(), fh, indent=2, default=str)
        print(f"\nRun artifact written to {args.out}")
    return 0


def _real_run(args: argparse.Namespace) -> AuditRun:
    strategist = AnthropicProvider(args.strategist, effort="high", max_tokens=8000)
    judge = AnthropicProvider(args.judge, effort="medium", name=f"judge:{args.judge}")
    candidates: list[Provider] = [AnthropicProvider(m) for m in args.candidates]
    pipeline = AuditPipeline(strategist=strategist, judge=judge)
    return pipeline.run(args.requirement, candidates)


def _demo_run() -> AuditRun:
    """A self-contained, deterministic run using mock providers only."""
    from .demo import build_demo

    pipeline, requirement, candidates = build_demo()
    return pipeline.run(requirement, candidates)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
