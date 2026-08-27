"""Central configuration. Everything secret comes from the environment."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val  # type: ignore[return-value]


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Config:
    VERSION = "0.1.0"
    PORT = int(os.environ.get("PORT", "8080"))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    ENV = os.environ.get("FLASK_ENV", "production")

    # Telegram
    TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", required=True)
    WEBHOOK_SECRET = _get("WEBHOOK_SECRET", default="ali_os_wh_secret")
    # Prefer explicit PUBLIC_URL; fall back to RENDER_EXTERNAL_URL on Render.
    PUBLIC_URL = (
        os.environ.get("PUBLIC_URL")
        or os.environ.get("RENDER_EXTERNAL_URL", "")
    ).rstrip("/")
    AUTO_SET_WEBHOOK = os.environ.get("AUTO_SET_WEBHOOK", "1") == "1"

    # LLM
    LLM_BASE_URL = _get("LLM_BASE_URL", default="https://inference.dahl.global/v1")
    LLM_API_KEY = _get("LLM_API_KEY", required=True)
    LLM_MODEL = os.environ.get("LLM_MODEL", "MiniMaxAI/MiniMax-M2.7")
    LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))
    LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1200"))

    # DB
    DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", str(DATA_DIR / "ali_os.db")))
    TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")
    TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

    # Ownership gate (P0 security): only these Telegram chat ids may command the bot.
    # Comma-separated for multiple owners. If UNSET → bot stays open (backward
    # compatible) and a warning is logged at startup — set it on Render!
    # Find your chat id by messaging the bot: /whoami
    TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "") or os.environ.get(
        "TELEGRAM_ADMIN_CHAT_IDS", ""
    )

    def admin_chat_ids(self) -> set[int]:
        # instance method (not classmethod): config is an instance and tests/ops
        # override TELEGRAM_ADMIN_CHAT_ID on it at runtime.
        out: set[int] = set()
        for part in self.TELEGRAM_ADMIN_CHAT_ID.replace("،", ",").replace("؛", ",").replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                out.add(int(part))
        return out

    # Cron / Automation (§16)
    CRON_SECRET = os.environ.get("CRON_SECRET", os.environ.get("WEBHOOK_SECRET", "ali_os_wh_9f3a7c2e8b1d"))
    # Content Agent
    CONTENT_DEFAULT_WORDS = int(os.environ.get("CONTENT_DEFAULT_WORDS", "2000"))

    @classmethod
    def webhook_url(cls) -> str:
        return f"{cls.PUBLIC_URL}/webhook" if cls.PUBLIC_URL else ""


config = Config()
