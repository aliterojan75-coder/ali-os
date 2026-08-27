"""Flask server — Telegram webhook + Mini App (admin dashboard).

Architecture:
    Telegram message → /webhook → Master Agent → LLM + DB
    Telegram Mini App → / (SPA) → /api/* (HMAC-authenticated) → DB

The request layer is stateless; all state lives in SQLite.
"""
from __future__ import annotations

from flask import Flask, jsonify, request

from app import approvals, seed
from app.config import config
from app.logging_config import get_logger, log_event
from app.master import MasterAgent
from app.master.agent import IncomingMessage
from app.miniapp.api import api as api_bp
from app.miniapp.routes import spa as spa_bp
from app.telegram import (
    answer_callback_query,
    parse_callback_query,
    parse_update,
    send_message,
    set_webhook,
)
from app.tools.set_menu import set_bot_commands, set_menu_button

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

        # Also wire the Telegram menu button → Mini App (web_app), so the
        # dashboard is reachable from the chat. Best-effort; never block boot.
        try:
            set_menu_button()
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram.set_menu_failed", extra={"extra_fields": {"error": str(exc)}})

        # Slash commands (/approvals, /dossier …). Best-effort; never block boot.
        try:
            set_bot_commands()
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram.set_commands_failed",
                        extra={"extra_fields": {"error": str(exc)}})

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

        # ── Inline button press on an approval card (§19) ──────────────────
        cb = parse_callback_query(update)
        if cb:
            log_event(
                log, "webhook.callback",
                user_id=cb.get("user_id"),
                payload={"data": cb.get("data"), "chat_id": cb.get("chat_id")},
            )
            try:
                if approvals.is_approval_callback(cb.get("data", "")):
                    approvals.handle_callback(cb)
                elif cb.get("callback_query_id"):
                    answer_callback_query(cb["callback_query_id"], "دکمه ناشناخته است.")
            except Exception as exc:  # noqa: BLE001 — never 500 back to Telegram
                log.exception("webhook.callback_error",
                              extra={"extra_fields": {"error": str(exc)}})
                if cb.get("callback_query_id"):
                    try:
                        answer_callback_query(cb["callback_query_id"], "خطای داخلی رخ داد.")
                    except Exception:  # noqa: BLE001
                        pass
            return jsonify({"ok": True})

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
            if answer is None:
                # The handler already replied itself (e.g. an approval card).
                return jsonify({"ok": True})
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
