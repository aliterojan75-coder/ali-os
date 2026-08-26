"""Minimal, dependency-free Telegram Bot API client.

We use raw requests instead of python-telegram-bot to keep the request layer
stateless and avoid event-loop / polling conflicts (§20, §49).
"""
from __future__ import annotations

import re
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
    parse_mode: str | None = "Markdown",  # render **bold**/italic (LLM uses markdown)
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    # Telegram has a 4096-char limit; chunk if needed. Keep < 4000 so we never
    # split mid-markdown or hit the cap.
    chunks = _chunk(text, 3900)
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
        try:
            result = _call("sendMessage", payload)
        except TelegramError:
            # Telegram can reject Markdown if the LLM produced a stray `_`, `*`
            # or unbalanced entity. Fall back to plain text (strip markers).
            fallback = dict(payload)
            fallback.pop("parse_mode", None)
            fallback["text"] = strip_markdown(chunk)
            result = _call("sendMessage", fallback)
    return result


def strip_markdown(text: str) -> str:
    """Remove Markdown emphasis tokens so the message renders as plain text.

    Keeps the content (and emojis); only strips the `**`, `*`, `__`, `_`, `##`
    markers that would otherwise be sent literally when parse_mode is off.
    """
    t = text
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)   # **bold**
    t = re.sub(r"__(.+?)__", r"\1", t)       # __bold__
    t = re.sub(r"(?<![\w*])\*(?!\*)(.+?)\*(?!\*)", r"\1", t)  # *italic*
    t = re.sub(r"(?<![\w_])\b_(?!_)(.+?)_(?![_w])", r"\1", t)  # _italic_
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)     # ## headings
    t = re.sub(r"`(.+?)`", r"\1", t)         # `code`
    return t


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        # try to break on newline (keeps sentences intact)
        nl = text.rfind("\n", start, end)
        if nl > start:
            end = nl
        # never break inside a **...** pair
        part = text[start:end]
        if part.count("**") % 2 != 0:
            # find the nearest newline before the end so a bold pair stays whole
            end = text.rfind("\n", start, end - 1) or end
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
