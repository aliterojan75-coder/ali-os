"""Flask server — Telegram webhook + Mini App (admin dashboard).

Architecture:
    Telegram message → /webhook → Master Agent → LLM + DB
    Telegram Mini App → / (SPA) → /api/* (HMAC-authenticated) → DB

The request layer is stateless; all state lives in SQLite.
"""
from __future__ import annotations

from flask import Flask, jsonify, request

from app import seed
from app.config import config
from app.logging_config import get_logger, log_event
from app.master import MasterAgent
from app.master.agent import IncomingMessage
from app.miniapp.api import api as api_bp
from app.miniapp.routes import spa as spa_bp
from app.telegram import parse_update, send_message, set_webhook

log = get_logger("webhook")

master = MasterAgent()


def create_app() -> Flask:
    app = Flask(__name__)

    # Initialise DB + seed on startup (idempotent).
    seed.seed_all()

    # Mini App + JSON API (registered before the webhook routes so "/" serves
    # the dashboard rather than a 404).
    app.register_blueprint(spa_bp)
    app.register_blueprint(api_bp)

    if config.AUTO_SET_WEBHOOK and config.webhook_url():
        try:
            set_webhook(config.webhook_url(), config.WEBHOOK_SECRET)
        except Exception as exc:  # noqa: BLE001
            log.warning("webhook.set_failed", extra={"extra_fields": {"error": str(exc)}})

    @app.get("/health")
    def health():
        return jsonify({
            "ok": True,
            "service": "ali-os",
            "version": config.VERSION,
            "model": config.LLM_MODEL,
        })

    @app.post("/webhook")
    def webhook():
        # Authenticate that the request really comes from Telegram (§48).
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if provided != config.WEBHOOK_SECRET:
            log.warning("webhook.unauthorized", extra={"extra_fields": {}})
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        update = request.get_json(silent=True) or {}
        parsed = parse_update(update)
        if not parsed or not parsed.get("user_id") or not parsed.get("text"):
            return jsonify({"ok": True, "ignored": True})

        log_event(
            log, "webhook.received",
            user_id=parsed["user_id"],
            payload={"chat_id": parsed["chat_id"], "text": parsed["text"][:80]},
        )

        try:
            answer = master.handle(IncomingMessage(
                user_id=parsed["user_id"],
                chat_id=parsed["chat_id"],
                text=parsed["text"],
                username=parsed.get("username"),
                first_name=parsed.get("first_name"),
            ))
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            log.exception("webhook.handler_error", extra={"extra_fields": {"error": str(exc)}})
            answer = "⚠️ خطای داخلی رخ داد."

        try:
            send_message(
                chat_id=parsed["chat_id"],
                text=answer,
                reply_to_message_id=parsed.get("message_id"),
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("webhook.send_failed", extra={"extra_fields": {"error": str(exc)}})

        return jsonify({"ok": True})

    return app


app = create_app()
