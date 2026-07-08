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

# Default Claude model IDs (see the claude-api skill catalog). Opus 4.8 is the
# most capable widely-released model — the natural "strategist".
STRATEGIST_MODEL = "claude-opus-4-8"
JUDGE_MODEL = "claude-sonnet-5"  # a different family/tier than most candidates, to
#                                  blunt self-preference bias (docs/RESEARCH.md §2)


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

    Streams so large ``max_tokens`` never trips the SDK's HTTP-timeout guard, and
    uses adaptive thinking + effort per the current API surface. The ``anthropic``
    package is imported lazily; install the ``anthropic`` extra to use this.
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
        if self._thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": self._effort}

        with client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
