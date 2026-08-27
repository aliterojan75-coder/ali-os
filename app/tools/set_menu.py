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


# Slash commands shown in the Telegram "/" menu (Phase 2 + Phase 3 start).
BOT_COMMANDS = [
    {"command": "start", "description": "معرفی و راهنما"},
    {"command": "tasks", "description": "Taskهای باز"},
    {"command": "approvals", "description": "صف تأیید (اقدامات در انتظار)"},
    {"command": "dossier", "description": "پرونده کامل پروژه — /dossier giahkade"},
    {"command": "connections", "description": "اتصال‌ها (وردپرس، گوگل، تلگرام…)"},
    {"command": "morning", "description": "گزارش صبحگاهی با تقویم شمسی"},
    {"command": "crm", "description": "مخاطبان و معاملات CRM"},
    {"command": "notify", "description": "اعلان‌ها — تسک معوق، تأیید، CRM"},
    {"command": "content", "description": "تولید محتوا — /content موضوع مقاله"},
    {"command": "seo", "description": "وضعیت سئو — Search Console + GA4"},
]


def set_bot_commands() -> bool:
    """Register the slash-command menu so Ali sees the Phase 2 commands."""
    _call("setMyCommands", {"commands": BOT_COMMANDS})
    log.info("telegram.set_commands_ok",
             extra={"extra_fields": {"count": len(BOT_COMMANDS)}})
    return True


if __name__ == "__main__":
    set_menu_button()
    set_bot_commands()
