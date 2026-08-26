"""Manually (re)register the Telegram webhook using config from the environment."""
from __future__ import annotations

from app.config import config
from app.telegram import set_webhook, delete_webhook, get_me


def main() -> None:
    me = get_me()
    print(f"Bot: @{me.get('username')} (id={me.get('id')})")
    if not config.webhook_url():
        print("PUBLIC_URL is not set. Set it in .env first.")
        return
    delete_webhook()
    result = set_webhook(config.webhook_url(), config.WEBHOOK_SECRET)
    print(f"Webhook set: {result}")
    print(f"URL: {config.webhook_url()}")


if __name__ == "__main__":
    main()
