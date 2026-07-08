"""Aggregate SessionScores into a difficulty-adjusted agent leaderboard.

The #1 trap in trace-based ranking is the **difficulty confound**: an agent handed
harder tasks looks worse even if it's better. Without correcting for it you rank the
*task allocation*, not the agent. We correct with a simple fixed-effects style
demeaning: each session's outcome is compared to the *baseline outcome for its
task_kind* (averaged across all agents), so every agent is judged against the same
per-task-kind bar. (A latent Elo/IRT model is the natural upgrade — noted for later.)

Sessions are weighted by ``confidence`` (hard-evidence sessions count more than
sentiment-only guesses), with a small floor so low-confidence sessions still count.
Ranking is by adjusted success, tie-broken by efficiency (fewer rounds/tokens to a
good outcome — the trait you actually hire for).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import mean

from .signals import SessionScore

_CONF_FLOOR = 0.25   # even a sentiment-only session carries some weight


@dataclass
class AgentRanking:
    agent: str
    n_sessions: int
    raw_success: float          # confidence-weighted mean outcome, unadjusted
    adjusted_success: float     # difficulty-adjusted (the ranking key)
    avg_rounds: float
    avg_tokens: float
    efficiency: float           # 0..1, higher = solved in fewer rounds/tokens
    top_failure_tags: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class Leaderboard:
    rankings: list[AgentRanking]
    task_kind_baselines: dict[str, float] = field(default_factory=dict)
    global_mean: float = 0.5

    def table(self) -> str:
        rows = ["rank  agent                 n   adj%  raw%  eff   rounds  tokens",
                "----  --------------------  --  ----  ----  ----  ------  ------"]
        for i, r in enumerate(self.rankings, 1):
            rows.append(f"{i:>4}  {r.agent[:20]:<20}  {r.n_sessions:>2}  "
                        f"{r.adjusted_success*100:>4.0f}  {r.raw_success*100:>4.0f}  "
                        f"{r.efficiency:>4.2f}  {r.avg_rounds:>6.1f}  {r.avg_tokens:>6.0f}")
        return "\n".join(rows)


def build_leaderboard(scores: list[SessionScore]) -> Leaderboard:
    if not scores:
        return Leaderboard(rankings=[])

    # --- per-task-kind difficulty baseline (across ALL agents) ---
    by_kind: dict[str, list[float]] = defaultdict(list)
    for s in scores:
        by_kind[s.task_kind].append(s.outcome)
    baselines = {k: mean(v) for k, v in by_kind.items()}
    global_mean = mean(s.outcome for s in scores)

    # --- group by agent ---
    per_agent: dict[str, list[SessionScore]] = defaultdict(list)
    for s in scores:
        per_agent[s.agent].append(s)

    # efficiency is normalized across agents, so gather raw per-agent stats first
    prelim: list[tuple[str, float, float, float, float, list[SessionScore]]] = []
    for agent, ss in per_agent.items():
        w = lambda x: max(_CONF_FLOOR, x.confidence)
        wsum = sum(w(x) for x in ss)
        raw = sum(x.outcome * w(x) for x in ss) / wsum
        # difficulty-adjusted: demean by task-kind baseline, re-center on global mean
        adj = global_mean + sum((x.outcome - baselines[x.task_kind]) * w(x)
                                for x in ss) / wsum
        adj = max(0.0, min(1.0, adj))
        good = [x for x in ss if x.outcome >= 0.5]
        avg_rounds = mean([x.rounds for x in good]) if good else mean([x.rounds for x in ss])
        avg_tokens = mean([x.tokens for x in good]) if good else mean([x.tokens for x in ss])
        prelim.append((agent, raw, adj, avg_rounds, avg_tokens, ss))

    # normalize efficiency: fewer rounds & tokens (among good sessions) => higher
    max_r = max(p[3] for p in prelim) or 1.0
    max_t = max(p[4] for p in prelim) or 1.0
    rankings: list[AgentRanking] = []
    for agent, raw, adj, avg_rounds, avg_tokens, ss in prelim:
        eff = 1.0 - 0.5 * (avg_rounds / max_r) - 0.5 * (avg_tokens / max_t)
        tags = Counter(t for x in ss for t in x.failure_tags)
        rankings.append(AgentRanking(
            agent=agent, n_sessions=len(ss),
            raw_success=round(raw, 3), adjusted_success=round(adj, 3),
            avg_rounds=round(avg_rounds, 2), avg_tokens=round(avg_tokens, 1),
            efficiency=round(max(0.0, eff), 3),
            top_failure_tags=tags.most_common(5),
        ))

    rankings.sort(key=lambda r: (r.adjusted_success, r.efficiency), reverse=True)
    return Leaderboard(rankings=rankings, task_kind_baselines=baselines,
                       global_mean=round(global_mean, 3))
