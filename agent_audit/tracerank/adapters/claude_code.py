"""Adapter: Claude Code session transcripts -> normalized Sessions.

Schema verified directly against real on-disk transcripts in this environment
(``~/.claude/projects/**``) — not guessed. Two file shapes share one schema:

* **Main transcript**: ``<projects_root>/<project-slug>/<sessionId>.jsonl`` — the
  top-level interactive session (JSON Lines, one record per event).
* **Subagent transcript**: ``<projects_root>/<project-slug>/<sessionId>/subagents/
  agent-<agentId>.jsonl`` (+ a sidecar ``agent-<agentId>.meta.json``) — one file per
  ``Agent``/``Task`` tool invocation. This is the cleaner unit: one bounded,
  single-purpose task per agent, the same granularity as a Copilot chat session —
  so it's the primary Session boundary here.

Verified record shapes (confirmed by reading real transcripts, fields below all
observed, not inferred):
* ``{"type":"user", "message":{"content": <str> | [block,...]}}`` — a block has
  ``type`` "text" (prose) or "tool_result" (``is_error: bool``, ``content``).
* ``{"type":"assistant", "message":{"content":[block,...], "model": "claude-...",
  "usage": {"input_tokens","output_tokens","cache_creation_input_tokens",
  "cache_read_input_tokens"}, "stop_reason": "end_turn"|"tool_use"|...}}`` — a block
  has ``type`` "text", "thinking" (skipped — not a user-facing outcome signal), or
  "tool_use".
* ``{"type":"system","subtype":"stop_hook_summary","preventedContinuation":bool,
  "hookErrors":[...]}`` — a Stop hook can *block* the agent from ending the turn,
  meaning it declared "done" prematurely; a genuinely Claude-Code-specific hard
  negative signal, folded in as a synthetic failed-tool turn.
* ``agent-<id>.meta.json``: ``{"agentType","description","toolUseId","spawnDepth"}``
  — ``description`` is the short human label given to the subagent (e.g.
  "haiku count t4"); used to infer ``task_kind``.

Token counts use the real ``usage`` numbers (input + both cache buckets + output),
matching how the rest of this project prices Anthropic usage (``providers.py``) —
far more accurate than a char/4 estimate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from ..model import Role, Session, Turn

_KNOWN_MODEL_WORDS = ("opus", "sonnet", "haiku", "gpt", "gemini", "claude",
                      "o1", "o3", "o4", "gpt-4o", "gpt4o", "mini")


def default_project_roots() -> list[Path]:
    root = Path.home() / ".claude" / "projects"
    return [root] if root.exists() else []


def iter_subagent_files(roots: Iterable[Path] | None = None) -> list[Path]:
    roots = list(roots) if roots is not None else default_project_roots()
    files: list[Path] = []
    for root in roots:
        files.extend(root.rglob("subagents/agent-*.jsonl"))
    return sorted(set(files))


def iter_main_session_files(roots: Iterable[Path] | None = None) -> list[Path]:
    """Top-level ``<sessionId>.jsonl`` files (siblings of a same-named subdir),
    excluding anything already under a ``subagents/`` directory."""
    roots = list(roots) if roots is not None else default_project_roots()
    files: list[Path] = []
    for root in roots:
        for p in root.rglob("*.jsonl"):
            if "subagents" not in p.parts:
                files.append(p)
    return sorted(set(files))


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
    except OSError:
        return []
    return records


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict) and block.get("type") == "text":
        return block.get("text", "") or ""
    return ""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(t for t in (_block_text(b) for b in content) if t).strip()
    return ""


def _tool_result_blocks(content: Any) -> list[dict]:
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def _usage_tokens(usage: dict) -> int:
    if not isinstance(usage, dict):
        return 0
    return (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
        + int(usage.get("output_tokens") or 0)
    )


def _iso_to_epoch(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _task_kind_from_description(desc: str) -> str:
    """meta.json 'description' is usually "<agent-ish word> <task label>"
    (a naming convention observed in this project's own subagent dispatches,
    e.g. "haiku count t4", "opus union-area") — strip a leading model-ish token
    so same-task runs across different agents share a task_kind bucket."""
    if not desc:
        return ""
    words = desc.strip().split()
    if words and any(w in words[0].lower() for w in _KNOWN_MODEL_WORDS):
        words = words[1:]
    # also drop a trailing trial marker like "t1".."t9"
    if words and re.fullmatch(r"t\d+", words[-1].lower()):
        words = words[:-1]
    return " ".join(words).strip().lower()


def _records_to_turns(records: list[dict]) -> tuple[list[Turn], dict[str, int], str | None]:
    """Shared line-record -> Turn[] extraction.
    Returns (turns, model -> assistant-turn-count, last_stop_reason)."""
    turns: list[Turn] = []
    model_counts: dict[str, int] = {}
    last_stop_reason: str | None = None
    for rec in records:
        t = rec.get("type")
        ts = _iso_to_epoch(rec.get("timestamp"))
        if t == "user":
            msg = rec.get("message", {}) if isinstance(rec.get("message"), dict) else {}
            content = msg.get("content")
            text = _content_text(content)
            if text:
                turns.append(Turn(Role.USER, text, ts=ts, tokens=max(1, len(text) // 4)))
            for tr in _tool_result_blocks(content):
                is_err = bool(tr.get("is_error"))
                body = tr.get("content")
                body_text = body if isinstance(body, str) else json.dumps(body)[:300]
                # Every tool_result carries hard evidence -- not just failures. Dropping
                # the successful ones would silently discard exactly the "hard pass"
                # signal (e.g. "all tests passed") the scorer is built to look for.
                prefix = "error: " if is_err else ""
                turns.append(Turn(Role.TOOL, f"{prefix}{body_text}", ts=ts,
                                  tool_ok=(not is_err), tokens=1))
        elif t == "assistant":
            msg = rec.get("message", {}) if isinstance(rec.get("message"), dict) else {}
            model = msg.get("model")
            if model:
                model_counts[model] = model_counts.get(model, 0) + 1
            last_stop_reason = msg.get("stop_reason", last_stop_reason)
            text = _content_text(msg.get("content"))
            usage = msg.get("usage") or {}
            if text:
                turns.append(Turn(Role.AGENT, text, ts=ts, tokens=_usage_tokens(usage) or max(1, len(text) // 4)))
        elif t == "system" and rec.get("subtype") == "stop_hook_summary":
            if rec.get("preventedContinuation") or rec.get("hookErrors"):
                turns.append(Turn(Role.TOOL,
                                  "stop_hook_blocked: agent tried to end the turn but a "
                                  "Stop hook judged the task incomplete", ts=ts,
                                  tool_ok=False, tokens=1))
    return turns, model_counts, last_stop_reason


def parse_subagent_file(path: str | Path) -> Session | None:
    path = Path(path)
    records = _read_jsonl(path)
    if not records:
        return None
    turns, model_counts, last_stop = _records_to_turns(records)
    if not turns:
        return None

    meta_path = path.with_suffix(".meta.json")
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}

    agent_model = max(model_counts, key=model_counts.get) if model_counts else None
    agent = agent_model or meta.get("agentType") or "claude-agent"
    task_kind = _task_kind_from_description(meta.get("description", ""))
    session_id = path.stem.removeprefix("agent-")
    return Session(
        session_id=session_id, agent=agent, turns=turns, task_kind=task_kind,
        source="claude-code", ended_naturally=(last_stop == "end_turn" or last_stop is None),
        meta={"path": str(path), "description": meta.get("description", "")},
    )


def parse_main_session_file(path: str | Path) -> Session | None:
    """Fallback: treat an entire top-level session transcript as one Session.
    Coarser than the subagent unit (one file may span many unrelated tasks and,
    if the model was switched mid-session, several models) — the reported
    ``agent`` is whichever model produced the most assistant turns."""
    path = Path(path)
    records = _read_jsonl(path)
    if not records:
        return None
    turns, model_counts, last_stop = _records_to_turns(records)
    if not turns:
        return None
    agent = max(model_counts, key=model_counts.get) if model_counts else "claude-agent"
    return Session(
        session_id=path.stem, agent=agent, turns=turns, task_kind="",
        source="claude-code", ended_naturally=(last_stop == "end_turn" or last_stop is None),
        meta={"path": str(path)},
    )


def load_sessions(roots: Iterable[Path] | None = None, *, files: Iterable[Path] | None = None,
                  include_main_sessions: bool = False) -> list[Session]:
    """Load subagent-task sessions (the primary unit); optionally also the coarser
    whole-conversation main-transcript sessions."""
    if files is not None:
        paths = list(files)
        out = []
        for p in paths:
            p = Path(p)
            s = parse_main_session_file(p) if "subagents" not in p.parts else parse_subagent_file(p)
            if s is not None:
                out.append(s)
        return out
    out = [s for p in iter_subagent_files(roots) if (s := parse_subagent_file(p)) is not None]
    if include_main_sessions:
        out += [s for p in iter_main_session_files(roots) if (s := parse_main_session_file(p)) is not None]
    return out
