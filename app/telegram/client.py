"""Minimal, dependency-free Telegram Bot API client.

We use raw requests instead of python-telegram-bot to keep the request layer
stateless and avoid event-loop / polling conflicts (§20, §49).
"""
from __future__ import annotations

from typing import Any

import requests

from app.config import config
from app.logging_config import get_logger

log = get_logger("telegram")

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


class TelegramError(RuntimeError):
    pass


def _call(method: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    try:
        resp = requests.post(f"{API}/{method}", json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise TelegramError(f"Telegram request failed: {exc}") from exc
    data = resp.json()
    if not data.get("ok"):
        # Never print the token; the description is safe.
        raise TelegramError(f"Telegram API error {data.get('error_code')}: {data.get('description')}")
    return data.get("result", {})


def set_webhook(url: str, secret: str) -> dict[str, Any]:
    log.info("telegram.set_webhook", extra={"extra_fields": {"url": url}})
    return _call("setWebhook", {"url": url, "secret_token": secret, "drop_pending_updates": True})


def delete_webhook() -> dict[str, Any]:
    return _call("deleteWebhook", {"drop_pending_updates": True})


def get_me() -> dict[str, Any]:
    return _call("getMe", {})


def send_message(
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = None,  # None: send as plain text (LLM outputs markdown-ish)
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    # Telegram has a 4096-char limit; chunk if needed.
    chunks = _chunk(text, 3800)
    result: dict[str, Any] = {}
    for i, chunk in enumerate(chunks):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if i == 0 and reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        result = _call("sendMessage", payload)
    return result


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        # try to break on newline
        nl = text.rfind("\n", start, end)
        if nl > start:
            end = nl
        parts.append(text[start:end].strip())
        start = end
    return [p for p in parts if p]


def parse_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise a Telegram update into a simple dict.

    Returns None for updates we don't handle (edited, channel, etc.).
    """
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    from_user = msg.get("from", {})
    chat = msg.get("chat", {})
    text = msg.get("text") or msg.get("caption") or ""
    if not text:
        return None
    return {
        "user_id": from_user.get("id"),
        "username": from_user.get("username"),
        "first_name": from_user.get("first_name"),
        "chat_id": chat.get("id"),
        "chat_type": chat.get("type"),
        "message_id": msg.get("message_id"),
        "text": text,
    }
