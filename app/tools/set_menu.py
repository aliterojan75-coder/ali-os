"""Set the Telegram bot menu button to launch the Ali OS Mini App."""
from __future__ import annotations

from app.config import config
from app.telegram.client import _call, get_me


def set_menu_button() -> None:
    base = config.PUBLIC_URL
    if not base:
        raise SystemExit("PUBLIC_URL is not set; cannot configure Mini App menu.")
    me = get_me()
    url = f"{base}/"
    print(f"Setting chat menu button for @{me.get('username')} → {url}")
    # Menu button visible in all private chats
    print(_call("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "داشبورد Ali OS",
            "web_app": {"url": url},
        }
    }))
    # Also an inline keyboard-attached "Open App" is possible, but the menu
    # button is the most natural entry point.
    print("✅ Menu button set.")


if __name__ == "__main__":
    set_menu_button()
