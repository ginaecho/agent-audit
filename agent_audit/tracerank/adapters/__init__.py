"""Source-specific adapters: native trace format -> normalized Session[].

Each adapter module exposes its own ``load_sessions(...)`` (signatures differ
slightly by source), so import the module rather than a flat re-export:

    from agent_audit.tracerank.adapters import copilot_vscode, claude_code
"""

from . import copilot_vscode, claude_code

__all__ = ["copilot_vscode", "claude_code"]
