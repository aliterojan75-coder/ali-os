"""Abstract LLM provider contract (§23).

Every concrete provider implements: chat, structured_output, stream,
model_info and health_check. The Master Agent only ever sees this interface.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator


@dataclass
class LLMMessage:
    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMError(RuntimeError):
    pass


class LLMProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        ...

    @abc.abstractmethod
    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        ...

    @abc.abstractmethod
    def structured_output(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Return a JSON object (with one retry on parse failure)."""
        ...

    @abc.abstractmethod
    def model_info(self) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    def health_check(self) -> bool:
        ...
