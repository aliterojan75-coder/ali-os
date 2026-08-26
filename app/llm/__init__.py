"""LLM layer.

The provider interface is the only thing the Master Agent depends on.
Swapping MiniMax for Kimi, OpenAI, Claude or a local model means adding a new
adapter — never rewriting the agent (§22–23).
"""
from .base import LLMProvider, LLMMessage, LLMResponse, LLMError  # noqa: F401
from .minimax_dahl import MiniMaxDahlProvider  # noqa: F401

_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = MiniMaxDahlProvider()
    return _provider
