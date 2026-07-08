"""Adapter: VS Code / GitHub Copilot Chat session transcripts -> normalized Sessions.

Grounded in VS Code source (microsoft/vscode `chat` contrib). The format has moved
around, so this parser is deliberately defensive and handles both layouts:

* **Flat JSON** (`<sessionId>.json`, older): one complete `ISerializableChatData`
  document per session.
* **Append-only JSONL** (`<sessionId>.jsonl`, newer default, gated by
  `chat.useLogSessionStorage`): a base record `{"kind":0,"v":{...}}` (full snapshot)
  followed by patch records `{"kind":1,"k":[path],"v":...}`. We replay the base +
  patches, and if that yields nothing usable we deep-scan every record for
  request-shaped objects (robust to the malformed files seen in vscode#308730 and
  to patch-semantics we haven't fully pinned down).

Storage locations (VS Code core `chatSessionStore.ts`):
  workspace chats: <userData>/workspaceStorage/<workspaceId>/chatSessions/*.json[l]
  empty-window:    <userData>/globalStorage/emptyWindowChatSessions/*.json[l]
  transferred:     <userData>/globalStorage/transferredChatSessions/*.json[l]
  <userData> = ~/.config/Code/User (Linux), ~/Library/Application Support/Code/User
  (macOS), %APPDATA%\\Code\\User (Windows); "Code" -> "Code - Insiders" for Insiders.
Per-turn status is `modelState` (ResponseModelState: 0 Pending,1 Complete,2 Cancelled,
3 Failed,4 NeedsInput); `vote` is ChatAgentVoteDirection (0 Down, 1 Up). The old
`isCanceled` is deprecated but still read as a fallback.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

from ..model import Role, Session, Turn

_SESSION_DIRS = ("chatSessions", "chatEditingSessions", "emptyWindowChatSessions",
                 "transferredChatSessions")
_REQUESTS_KEYS = ("requests", "exchanges", "turns")
_MSG_KEYS = ("message", "request", "userMessage")
_RESP_KEYS = ("response", "responseParts", "responseText", "agentResponse")
_TEXT_KEYS = ("text", "value", "message", "content", "label", "kindText")
_AGENT_KEYS = ("responderUsername", "responder", "agent", "modelId")
_TS_KEYS = ("timestamp", "creationDate", "time")

# ResponseModelState (chatService.ts)
_STATE_CANCELLED, _STATE_FAILED = 2, 3


def default_storage_roots() -> list[Path]:
    """Best-effort VS Code user-data roots for the current OS (stable + Insiders)."""
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", home))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    roots = [base / v / "User" for v in ("Code", "Code - Insiders", "VSCodium")]
    return [r for r in roots if r.exists()]


def iter_session_files(roots: Iterable[Path] | None = None) -> list[Path]:
    """Find chat-session files (.json and .jsonl) under the given/default roots."""
    roots = list(roots) if roots is not None else default_storage_roots()
    files: list[Path] = []
    for root in roots:
        for sub in _SESSION_DIRS:
            files.extend(root.rglob(f"{sub}/*.json"))
            files.extend(root.rglob(f"{sub}/*.jsonl"))
    return sorted(set(files))


def _first(d: Any, keys: tuple[str, ...], default=None):
    if isinstance(d, dict):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
    return default


def _text_of(obj: Any) -> str:
    """Recursively pull human-readable text from VS Code's varied part shapes."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(t for t in (_text_of(x) for x in obj) if t).strip()
    if isinstance(obj, dict):
        for k in _TEXT_KEYS:
            if k in obj:
                return _text_of(obj[k])
        if "parts" in obj:
            return _text_of(obj["parts"])
    return ""


def _vote_of(req: dict) -> int | None:
    """ChatAgentVoteDirection: 1=Up->+1, 0=Down->-1 (only when explicitly present)."""
    if "vote" not in req and "feedback" not in req:
        return None
    v = req.get("vote", req.get("feedback"))
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return 1 if v == 1 else (-1 if v == 0 else None)
    if isinstance(v, str):
        s = v.lower()
        return 1 if s in ("up", "helpful", "positive") else (-1 if s in ("down", "unhelpful", "negative") else None)
    if isinstance(v, dict):
        return _vote_of({"vote": v.get("direction", v.get("kind"))})
    return None


def _status(req: dict) -> tuple[bool, str]:
    """Return (canceled, error_text) using modern modelState then legacy fallbacks."""
    st = req.get("modelState")
    state = st.get("state") if isinstance(st, dict) else st
    result = req.get("result") or {}
    err = (result.get("errorDetails") or {}).get("message") or ""
    canceled = state == _STATE_CANCELLED or bool(req.get("isCanceled"))
    failed = state == _STATE_FAILED
    if failed and not err:
        err = "error: response failed"
    if err:
        err = err if err.lower().startswith("error") else f"error: {err}"
    return canceled, err


_SLASH_KIND = {"fix": "debug", "tests": "test", "test": "test", "explain": "explain",
               "doc": "docs", "new": "scaffold", "newNotebook": "scaffold"}


def _infer_task_kind(first_user_text: str, req0: dict) -> str:
    sc = req0.get("slashCommand") or req0.get("command")
    if isinstance(sc, dict):
        sc = sc.get("name", "")
    if isinstance(sc, str) and sc in _SLASH_KIND:
        return _SLASH_KIND[sc]
    t = (first_user_text or "").lower()
    for kw, kind in (("debug", "debug"), ("fix", "debug"), ("crash", "debug"),
                     ("test", "test"), ("refactor", "refactor"), ("explain", "explain"),
                     ("error", "debug"), ("implement", "feature"), ("add", "feature")):
        if kw in t:
            return kind
    return ""


def _agent_of(data: dict, requests: list) -> str:
    for req in requests:
        if isinstance(req, dict):
            mid = req.get("modelId")
            if mid:
                return str(mid)
            ag = req.get("agent")
            if isinstance(ag, dict) and (ag.get("id") or ag.get("fullName")):
                return str(ag.get("fullName") or ag.get("id"))
    return _text_of(_first(data, _AGENT_KEYS)) or "copilot"


# --- JSONL (base + patch) support -------------------------------------------
def _apply_patch(root: Any, path: list, value: Any) -> None:
    """Best-effort replay of a patch record onto the reconstructed root."""
    if not isinstance(path, list) or not path:
        return
    cur = root
    for key in path[:-1]:
        if isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        elif isinstance(cur, dict):
            cur = cur.setdefault(key, {})
        else:
            return
    last = path[-1]
    if isinstance(cur, list):                       # push onto a list
        cur.extend(value if isinstance(value, list) else [value])
    elif isinstance(cur, dict):
        if isinstance(cur.get(last), list) and isinstance(value, list):
            cur[last].extend(value)
        else:
            cur[last] = value


def _scan_request_like(records: list[dict]) -> list[dict]:
    """Fallback: harvest request-shaped dicts from anywhere in the records."""
    found: list[dict] = []
    seen: set[int] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "message" in o and any(k in o for k in ("response", "responseId", "result", "modelId")):
                rid = id(o)
                if rid not in seen:
                    seen.add(rid)
                    found.append(o)
                return
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    for r in records:
        walk(r.get("v") if isinstance(r, dict) else r)
    return found


def _read_chat_data(path: Path) -> dict | None:
    """Return a dict with at least a 'requests' list, from .json or .jsonl."""
    try:
        raw = path.read_text(encoding="utf-8-sig")  # tolerate BOM
    except OSError:
        return None
    if path.suffix == ".jsonl":
        records: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)
        if not records:
            return None
        base = next((r.get("v") for r in records if r.get("kind") == 0
                     and isinstance(r.get("v"), dict)), None)
        root = dict(base) if isinstance(base, dict) else {}
        for rec in records:
            if rec.get("kind") not in (0, None) and "k" in rec:
                _apply_patch(root, rec.get("k"), rec.get("v"))
        reqs = _first(root, _REQUESTS_KEYS)
        if not (isinstance(reqs, list) and reqs):
            root.setdefault("requests", _scan_request_like(records))
        return root
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_session_file(path: str | Path) -> Session | None:
    """Parse one VS Code chat-session file (.json or .jsonl) into a Session."""
    path = Path(path)
    data = _read_chat_data(path)
    if data is None:
        return None
    requests = _first(data, _REQUESTS_KEYS, []) or []
    if not isinstance(requests, list) or not requests:
        return None

    turns: list[Turn] = []
    last_canceled = False
    first_user_text = ""
    for i, req in enumerate(requests):
        if not isinstance(req, dict):
            continue
        user_text = _text_of(_first(req, _MSG_KEYS, ""))
        if i == 0:
            first_user_text = user_text
        ts = _first(req, _TS_KEYS)
        ts = float(ts) / (1000.0 if ts and ts > 1e11 else 1.0) if isinstance(ts, (int, float)) else None
        if user_text:
            turns.append(Turn(Role.USER, user_text, ts=ts,
                              tokens=max(1, len(user_text) // 4), vote=_vote_of(req)))
        resp_text = _text_of(_first(req, _RESP_KEYS, ""))
        canceled, err = _status(req)
        last_canceled = canceled
        full = (resp_text + (" " + err if err else "")).strip()
        turns.append(Turn(Role.AGENT, full, ts=ts, tokens=max(1, len(full) // 4),
                          canceled=canceled, meta={"error": err} if err else {}))

    if not turns:
        return None
    return Session(
        session_id=path.stem, agent=_agent_of(data, requests), turns=turns,
        task_kind=_infer_task_kind(first_user_text, requests[0] if requests else {}),
        source="copilot-vscode", ended_naturally=(not last_canceled),
        meta={"path": str(path)},
    )


def load_sessions(roots: Iterable[Path] | None = None,
                  *, files: Iterable[Path] | None = None) -> list[Session]:
    """Load and normalize all Copilot chat sessions (from ``files`` or discovered roots)."""
    paths = list(files) if files is not None else iter_session_files(roots)
    out: list[Session] = []
    for p in paths:
        s = parse_session_file(p)
        if s is not None:
            out.append(s)
    return out
