"""Set the Telegram bot menu button to launch the Ali OS Mini App."""
from __future__ import annotations

from app.config import config
from app.logging_config import get_logger
from app.telegram.client import _call, get_me

log = get_logger("telegram")


def set_menu_button() -> bool:
    base = config.PUBLIC_URL
    if not base:
        log.warning("telegram.set_menu_no_url", extra={"extra_fields": {}})
        return False
    me = get_me()
    url = f"{base}/"
    log.info("telegram.set_menu", extra={"extra_fields": {"username": me.get("username"), "url": url}})
    # Menu button visible in all private chats
    _call("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "داشبورد دستیار علی",
            "web_app": {"url": url},
        }
    })
    log.info("telegram.set_menu_ok", extra={"extra_fields": {}})
    return True


if __name__ == "__main__":
    set_menu_button()
