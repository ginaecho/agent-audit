"""Provider abstraction.

A ``Provider`` is anything that can turn a prompt into a text answer. Two kinds
matter for this project:

* the **strategist** and the **judge** are providers used by the framework itself;
* every **candidate** under audit is also just a provider — which is the point:
  candidates can be different Claude models, or arbitrary agents (a function that
  wraps tools, memory, scaffolding), screened on equal footing.

The engine has zero hard dependencies. ``MockProvider`` lets the whole pipeline —
strategist, candidates, and judge — run offline and deterministically (used by the
demo and the test suite). ``AnthropicProvider`` screens real Claude models; it
imports ``anthropic`` lazily so the package installs and runs without it.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

# --- Model policy -------------------------------------------------------------
# Three separate parties, so the exam author, the grader, and the examinees never
# coincide (self-preference bias, docs/RESEARCH.md §2):
#   * strategist authors the audit  -> Opus 4.8 (most capable non-Fable model)
#   * judge grades open-ended checks -> Opus 4.7 (strong, and NOT a candidate)
#   * candidates under audit         -> the four models below (no Fable 5 anywhere)
STRATEGIST_MODEL = "claude-opus-4-8"
JUDGE_MODEL = "claude-opus-4-7"
CANDIDATE_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]

# USD per million tokens (input, output) — used for the harness cost accounting.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def _supports_modern_params(model: str) -> bool:
    """Whether the model accepts adaptive thinking + output_config.effort.

    Claude 4.6+ models do; Haiku 4.5 / Sonnet 4.5 and older reject ``effort`` and
    have no adaptive thinking — sending those params would 400 the request.
    """
    if "haiku" in model:
        return False
    if model.startswith(("claude-sonnet-4-5", "claude-opus-4-5", "claude-3", "claude-opus-4-0",
                         "claude-opus-4-1", "claude-sonnet-4-0", "claude-opus-4-2")):
        return False
    return True


@runtime_checkable
class Provider(Protocol):
    name: str

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Return a text completion for ``prompt``."""
        ...


class FunctionProvider:
    """Wrap any ``(prompt, system) -> str`` callable as a Provider.

    This is how a heterogeneous *agent* (not just a raw model) enters the audit:
    give it a name and a function that runs the agent and returns its final text.
    """

    def __init__(self, name: str, fn: Callable[[str, str | None], str]) -> None:
        self.name = name
        self._fn = fn

    def complete(self, prompt: str, system: str | None = None) -> str:
        return self._fn(prompt, system)


class MockProvider:
    """Deterministic offline provider.

    ``responder`` receives ``(prompt, system)`` and returns the answer. Used to run
    the pipeline with no network / no API key (demo + tests). A plain string makes a
    constant provider that always returns that string.
    """

    def __init__(self, name: str, responder: Callable[[str, str | None], str] | str) -> None:
        self.name = name
        if isinstance(responder, str):
            const = responder
            self._responder: Callable[[str, str | None], str] = lambda p, s: const
        else:
            self._responder = responder

    def complete(self, prompt: str, system: str | None = None) -> str:
        return self._responder(prompt, system)


class AnthropicProvider:
    """Screen a real Claude model via the official Anthropic SDK.

    Streams so large ``max_tokens`` never trips the SDK's HTTP-timeout guard. On
    4.6+ models it uses adaptive thinking + effort; on older models (Haiku 4.5,
    Sonnet 4.5, ...) those params are omitted automatically — they would 400.
    Token usage is accumulated on ``self.usage`` and priced by ``cost_usd()`` so
    the harness can report quality *and* cost. The ``anthropic`` package is
    imported lazily; install the ``anthropic`` extra to use this.
    """

    def __init__(
        self,
        model: str,
        name: str | None = None,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        effort: str = "medium",
        thinking: bool = True,
        client: object | None = None,
    ) -> None:
        self.model = model
        self.name = name or model
        self._system = system
        self._max_tokens = max_tokens
        self._effort = effort
        self._thinking = thinking
        self._client = client  # inject a client in tests; else created lazily
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def cost_usd(self) -> float:
        """Approximate spend so far (ignores prompt-cache discounts)."""
        inp, out = PRICING_USD_PER_MTOK.get(self.model, (5.00, 25.00))
        return (self.usage["input_tokens"] * inp + self.usage["output_tokens"] * out) / 1e6

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on optional dep
                raise ImportError(
                    "AnthropicProvider requires the 'anthropic' package. "
                    "Install it with:  pip install 'agent-audit[anthropic]'"
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, prompt: str, system: str | None = None) -> str:
        client = self._get_client()
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        sys = system if system is not None else self._system
        if sys:
            kwargs["system"] = sys
        if _supports_modern_params(self.model):
            if self._thinking:
                kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": self._effort}

        with client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        usage = getattr(message, "usage", None)
        if usage is not None:
            self.usage["input_tokens"] += (
                (getattr(usage, "input_tokens", 0) or 0)
                + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
                + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            )
            self.usage["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )


class SkilledProvider:
    """An *agent* = a base provider + a skill (instructions / lessons / scaffolding).

    This is how "agent A vs. agent B" enters the audit: B is A wearing a better
    skill. The skill text is prepended to the system prompt on every call, so the
    same audit that screened A can measure exactly how much the skill moved B —
    and the coach's ``ImprovementPlan.skill_text`` (see ``coach.py``) plugs in here
    to close the audit -> guidance -> improve -> re-audit loop.
    """

    def __init__(self, base: Provider, skill: str, name: str | None = None) -> None:
        self.base = base
        self.skill = skill
        self.name = name or f"{base.name}+skill"

    def complete(self, prompt: str, system: str | None = None) -> str:
        merged = self.skill if not system else f"{self.skill}\n\n{system}"
        return self.base.complete(prompt, system=merged)

    def cost_usd(self) -> float:
        cost = getattr(self.base, "cost_usd", None)
        return cost() if callable(cost) else 0.0
