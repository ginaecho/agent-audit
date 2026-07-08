"""Runnable example: screen three candidates for a billing-desk assistant, offline.

    python examples/customer_support.py

This uses the package's built-in offline demo (mock strategist, judge, and
candidates) so it runs with no API key and is fully deterministic. To screen real
Claude models instead, replace the mock providers with ``AnthropicProvider`` — see
the commented block at the bottom.
"""

from __future__ import annotations

import json
import os

from agent_audit.demo import build_demo


def main() -> None:
    pipeline, requirement, candidates = build_demo()
    run = pipeline.run(requirement, candidates)

    print(run.summary())

    os.makedirs("runs", exist_ok=True)
    out = "runs/customer_support.audit.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(run.to_dict(), fh, indent=2, default=str)
    print(f"\nFull auditable run artifact written to {out}")


# --- To screen real Claude models, use this instead of build_demo(): ---------
#
#   from agent_audit import AuditPipeline, AnthropicProvider
#
#   pipeline = AuditPipeline(
#       strategist=AnthropicProvider("claude-opus-4-8", effort="high", max_tokens=8000),
#       judge=AnthropicProvider("claude-sonnet-5", name="judge"),
#   )
#   candidates = [
#       AnthropicProvider("claude-haiku-4-5"),
#       AnthropicProvider("claude-sonnet-5"),
#       AnthropicProvider("claude-opus-4-8"),
#   ]
#   run = pipeline.run(requirement, candidates)
#
# Requires:  pip install 'agent-audit[anthropic]'  and ANTHROPIC_API_KEY (or an
# `ant auth login` profile).


if __name__ == "__main__":
    main()
