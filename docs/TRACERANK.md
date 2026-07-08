# tracerank — rank agents from real usage, not synthetic tests

Auto-generating a discriminating benchmark hits a ceiling: a model can't author
items past its own blind spots, most tests tie (we spent ~16 Opus rounds to find
one gap — see `RESULTS.md`/`FINDINGS_AND_OPEN_PROBLEMS.md`), and anything it authors
is trivial to overfit. `tracerank` takes the other road: **harvest ground truth that
already exists** — the outcomes of real agent sessions — and rank agents by inferred
task success, difficulty-adjusted, then emit per-agent improvement *skills*.

## Use it

```bash
python -m agent_audit.tracerank --demo                       # bundled Copilot sample
python -m agent_audit.tracerank --list-roots                 # show where it will look
python -m agent_audit.tracerank                               # your real VS Code / Copilot chats
python -m agent_audit.tracerank --source claude-code           # your real Claude Code sessions
python -m agent_audit.tracerank --source claude-code --demo   # bundled Claude Code sample
python -m agent_audit.tracerank --json                        # machine-readable output
```

Runs entirely locally; trace contents never leave your machine.

## Pipeline

```
adapter (source-specific)  ->  normalized Session[]     (model.py)
Session                    ->  SessionScore             (signals.py)
SessionScore[]             ->  difficulty-adjusted board (leaderboard.py)
recurring failures         ->  per-agent skill hints     (hints.py)
```

The scoring reuses the project's thesis: an **outcome** signal (did the task
succeed?) combined with **efficiency** (rounds/tokens to satisfaction), and —
crucially — **difficulty-adjusted** so an agent handed harder work isn't penalised.

## Signal hierarchy (weight hard >> soft)

- **Hard (verifiable in the trace):** tests passed / build ok / commit landed → +;
  tests failed / build error / `modelState: Failed` / revert → −. Near-ground-truth.
- **Medium:** rounds- and tokens-to-satisfaction; explicit re-asks ("still broken",
  "again"); a canceled/`Cancelled` final turn; explicit thumbs `vote`.
- **Soft (sentiment):** "thanks/perfect/works" → +; "no/wrong/useless" + anger → −.
  Useful but noisy — never decisive alone; `confidence` is low when only soft signals
  fire, so the leaderboard down-weights those sessions.

## The traps it handles (and the ones it doesn't)

- **Difficulty confound (handled):** each session's outcome is demeaned against the
  average outcome for its `task_kind`, so agents are judged against the same per-kind
  bar — otherwise you'd rank *task allocation*, not capability. (Latent Elo/IRT is the
  natural upgrade.)
- **Proxy noise (partly handled):** hard signals dominate; sentiment-only sessions get
  low `confidence`. For the residue, a strong model can relabel low-confidence
  sessions *anchored to the transcript* (grading past real work, so no self-reference
  ceiling) — a documented extension point, not yet wired.
- **Not handled / caveats:** selection bias (which tasks went to which agent isn't
  random); reward-hacking if agents learn the metric; privacy (summarise/redact
  locally); attribution in multi-agent chains. Small session counts make the
  difficulty adjustment noisy (an agent alone in a task bucket regresses to the mean).

## VS Code / Copilot adapter — the on-disk format

Grounded in `microsoft/vscode` source (`chat` contrib). Handles both layouts:

- **Flat JSON** `<sessionId>.json` (older): one `ISerializableChatData` doc.
- **Append-only JSONL** `<sessionId>.jsonl` (newer default, `chat.useLogSessionStorage`):
  a base record `{"kind":0,"v":{…}}` + patch records `{"kind":1,"k":[path],"v":…}`,
  replayed; with a deep-scan fallback for request-shaped objects if replay yields
  nothing (robust to malformed files, cf. vscode#308730).

Locations (`chatSessionStore.ts`): `workspaceStorage/<id>/chatSessions/`,
`globalStorage/emptyWindowChatSessions/`, `globalStorage/transferredChatSessions/`
under the VS Code user-data dir (`~/.config/Code/User` Linux, `~/Library/Application
Support/Code/User` macOS, `%APPDATA%\Code\User` Windows; `Code - Insiders` for
Insiders). Per-turn status = `modelState` (0 Pending, 1 Complete, 2 Cancelled,
3 Failed, 4 NeedsInput); `vote` = `ChatAgentVoteDirection` (0 Down, 1 Up); legacy
`isCanceled` read as fallback. The parser tries multiple field names per value, so a
schema bump usually means editing one small candidate list in `copilot_vscode.py`.

*The format shifts across releases — run `--list-roots` and eyeball a parsed session
before trusting a run. Adding a new source (Copilot CLI, other IDEs) is one new
adapter that emits `Session[]`; everything downstream is shared.*

## Claude Code adapter — the on-disk format

Schema verified directly against real transcripts in this environment
(`~/.claude/projects/**`), not guessed. Two file shapes, one schema:

- **Main transcript** `<projects_root>/<slug>/<sessionId>.jsonl` — the whole
  interactive session as one JSON-Lines stream.
- **Subagent transcript** `<projects_root>/<slug>/<sessionId>/subagents/
  agent-<id>.jsonl` (+ sidecar `agent-<id>.meta.json` with `description`/
  `agentType`) — one bounded, single-purpose task per file. This is the primary
  ranking unit (`parse_subagent_file`) — same granularity as a Copilot chat
  session. `--include-main-sessions` also loads the coarser whole-conversation
  unit as a fallback.

Confirmed fields: `{"type":"user","message":{"content": str | [block,...]}}`
(a block is `text` prose or `tool_result` with `is_error`); `{"type":"assistant",
"message":{"content":[...], "model", "usage":{"input_tokens","output_tokens",
"cache_creation_input_tokens","cache_read_input_tokens"}, "stop_reason"}}`.
Token counts use the real `usage` numbers (matching how `providers.py` prices
Anthropic usage), not a char/4 estimate. A genuinely Claude-Code-specific hard
signal: `{"type":"system","subtype":"stop_hook_summary","preventedContinuation":
bool,"hookErrors":[...]}` — a Stop hook can block the agent from ending the turn,
meaning it declared "done" prematurely; folded in as a synthetic failed-tool turn.

**A real bug the fixtures caught:** the first adapter draft only emitted a Turn
for `is_error: true` tool results, silently discarding successful ones — which
threw away exactly the "hard pass" evidence (e.g. "all tests passed") the scorer
depends on. Fixed (`_records_to_turns` now surfaces every `tool_result`,
`tool_ok = not is_error`); regression-tested (`test_claude_code_adapter_surfaces_
successful_tool_results`).

### Honest finding from validating against this environment's own traces

Running the adapter against the ~100+ real subagent transcripts already on disk
in this session surfaced a genuine limitation, not a success story to round up:
**single-shot Q&A subagents carry no embedded outcome signal.** Several dozen of
those sessions were "answer this reasoning problem, return one line" subagents —
one user turn, one assistant turn, **zero tool calls** — whose correctness was
judged *externally*, in the orchestrating conversation (comparing the final
answer against ground truth), never written back into the subagent's own trace.
With no test run, no vote, no follow-up correction inside the file itself, the
signal hierarchy has nothing hard to grab and the three models land close to a
flat baseline (~60% each) — which is *not* what a hand-graded pass, matching
the reliability-sweep result in `RESULTS.md` (opus/sonnet ~100%, haiku ~65%),
would show if the grading were visible in-trace.

**The takeaway:** trace-based ranking is only as good as the evidence embedded
*in the trace*. It works well for interactive, verifiable work (a coding agent
that runs tests, a chat where the user pushes back) and says almost nothing about
isolated single-shot generations graded elsewhere. If you want to rank agents on
Q&A-style work, either (a) have the grading step write its verdict back into the
same trace (a vote, a labeled tool_result), or (b) use the strong-model
transcript-relabeler extension point noted above instead of the raw heuristics.
