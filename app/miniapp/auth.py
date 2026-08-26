"""Telegram Mini App initData validation.

Telegram sends a signed `initData` query string to the mini app. The frontend
forwards it in the `X-Telegram-Init-Data` header and we verify it exactly as
documented:

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = HMAC_SHA256(key=secret_key, msg=data_check_string)

where data_check_string is every field except `hash`, sorted by key and joined
with newlines as `key=value`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from app.config import config
from app.logging_config import get_logger

log = get_logger("miniapp.auth")

MAX_AGE_SECONDS = 24 * 60 * 60  # reject initData older than 24h


def verify_init_data(init_data: str, *, max_age: int = MAX_AGE_SECONDS) -> dict | None:
    """Return the parsed user dict if valid and fresh, else None."""
    if not init_data:
        return None

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception:  # noqa: BLE001
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(pairs.items(), key=lambda kv: kv[0])
    )

    secret_key = hmac.new(
        b"WebAppData", config.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    computed = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        log.warning("miniapp.bad_hash", extra={"extra_fields": {}})
        return None

    # Freshness
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age and (time.time() - auth_date) > max_age:
        log.warning("miniapp.stale", extra={"extra_fields": {"age": int(time.time() - auth_date)}})
        return None

    user = {}
    if pairs.get("user"):
        try:
            user = json.loads(pairs["user"])
        except json.JSONDecodeError:
            user = {}
    return user


def sign_init_data_for_test(fields: dict) -> str:
    """Only used in tests/dev to produce a valid initData string."""
    import hmac as _hmac
    import hashlib as _hl
    from urllib.parse import urlencode

    data = dict(fields)
    data.setdefault("auth_date", str(int(time.time())))
    if "user" in data and isinstance(data["user"], dict):
        data["user"] = json.dumps(data["user"], separators=(",", ":"))

    dcs = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    sk = _hmac.new(b"WebAppData", config.TELEGRAM_BOT_TOKEN.encode(), _hl.sha256).digest()
    data["hash"] = _hmac.new(sk, dcs.encode(), _hl.sha256).hexdigest()
    return urlencode(data)
