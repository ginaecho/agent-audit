"""Source-specific adapters: native trace format -> normalized Session[]."""

from .copilot_vscode import load_sessions, parse_session_file, default_storage_roots

__all__ = ["load_sessions", "parse_session_file", "default_storage_roots"]
