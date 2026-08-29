"""LLM layer.

The provider interface is the only thing the Master Agent depends on. The
default adapter is provider-neutral OpenAI-compatible HTTP, so Gemini,
OpenAI-compatible gateways, or self-hosted compatible endpoints can be swapped
with environment variables — without rewriting the agent (§22–23).
"""
from .base import LLMProvider, LLMMessage, LLMResponse, LLMError  # noqa: F401
from .openai_compatible import OpenAICompatibleProvider  # noqa: F401

_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = OpenAICompatibleProvider()
    return _provider
