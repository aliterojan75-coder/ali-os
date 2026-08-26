"""MiniMax-M2.7 via the Dahl inference endpoint.

The endpoint is OpenAI-compatible (/v1/chat/completions), so this adapter is a
thin, defensive HTTP client. It implements the full LLMProvider contract.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import requests

from app.config import config
from app.logging_config import get_logger

from .base import LLMError, LLMMessage, LLMProvider, LLMResponse

log = get_logger("llm.minimax")

# MiniMax-M2.7 emits reasoning wrapped in <think>...</think>. We keep it out of
# user-facing answers (but could store it later for audit/debug).
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


def strip_reasoning(text: str) -> str:
    if THINK_OPEN in text and THINK_CLOSE in text:
        before, rest = text.split(THINK_OPEN, 1)
        _, after = rest.split(THINK_CLOSE, 1)
        return (before + after).strip()
    # Sometimes the close tag arrives but content after it is the answer
    if text.startswith(THINK_OPEN):
        idx = text.find(THINK_CLOSE)
        if idx != -1:
            return text[idx + len(THINK_CLOSE):].strip()
    return text.strip()


class MiniMaxDahlProvider(LLMProvider):
    name = "minimax-m2.7-dahl"

    def __init__(self) -> None:
        self.base_url = config.LLM_BASE_URL.rstrip("/")
        self.api_key = config.LLM_API_KEY
        self.model = config.LLM_MODEL
        self.timeout = config.LLM_TIMEOUT
        self.max_tokens = config.LLM_MAX_TOKENS
        self._session = requests.Session()

    # ── HTTP ───────────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int | None,
        stream: bool,
        response_format: dict | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.content
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": stream,
        }
        if response_format:
            payload["response_format"] = response_format
        return payload

    def _post(self, payload: dict[str, Any], stream: bool = False) -> requests.Response:
        url = f"{self.base_url}/chat/completions"
        try:
            resp = self._session.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                stream=stream,
            )
        except requests.RequestException as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        if resp.status_code >= 400:
            # Never log the key; just status + body
            raise LLMError(
                f"LLM returned HTTP {resp.status_code}: {resp.text[:500]}"
            )
        return resp

    # ── Contract ───────────────────────────────────────────────────────────
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        payload = self._payload(messages, temperature, max_tokens, False, response_format)
        resp = self._post(payload, stream=False)
        data = resp.json()
        return self._to_response(data)

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        payload = self._payload(messages, temperature, max_tokens, True, None)
        resp = self._post(payload, stream=True)
        buffer = ""
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.removeprefix("data:").strip()
            if line == "[DONE]":
                break
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            delta = (
                chunk.get("choices", [{}])[0]
                .get("delta", {})
                .get("content")
            )
            if delta:
                # Hold back while inside a <think> block so reasoning doesn't
                # leak to the user mid-stream.
                buffer += delta
                if THINK_OPEN in buffer and THINK_CLOSE not in buffer:
                    continue
                if THINK_CLOSE in buffer:
                    buffer = strip_reasoning(buffer)
                yield buffer
                buffer = ""
        if buffer:
            yield strip_reasoning(buffer)

    def structured_output(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        # Two attempts: plain JSON-mode, then a repair prompt.
        payload_msgs = list(messages)
        for attempt in range(2):
            if attempt == 1:
                payload_msgs.append(
                    LLMMessage(
                        role="user",
                        content=(
                            "پاسخ قبلی JSON معتبر نبود. فقط یک شیء JSON معتبر "
                            "برگردان، بدون هیچ متن اضافی، بدون تگ <think>."
                        ),
                    )
                )
            response_format = {"type": "json_object"}
            resp = self.chat(
                payload_msgs,
                temperature=temperature,
                max_tokens=max_tokens or self.max_tokens,
                response_format=response_format,
            )
            parsed = _extract_json(resp.content)
            if parsed is not None:
                return parsed
            log.warning("llm.json_parse_failed", extra={"extra_fields": {"attempt": attempt}})
        raise LLMError("Failed to parse structured JSON after retries")

    def model_info(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "max_tokens_default": self.max_tokens,
        }

    def health_check(self) -> bool:
        try:
            r = self.chat(
                [LLMMessage(role="user", content="ping")],
                max_tokens=5,
                temperature=0.0,
            )
            return bool(r.content)
        except Exception as exc:  # noqa: BLE001
            log.warning("llm.health_failed", extra={"extra_fields": {"error": str(exc)}})
            return False

    # ── Internals ──────────────────────────────────────────────────────────
    def _to_response(self, data: dict[str, Any]) -> LLMResponse:
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        content = strip_reasoning(msg.get("content", "") or "")
        usage = data.get("usage", {}) or {}
        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            raw=data,
        )


def _extract_json(text: str) -> dict[str, Any] | None:
    text = strip_reasoning(text).strip()
    if text.startswith("```"):
        # strip code fences
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
