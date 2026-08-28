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

# P0: per-chat cooldown for the polite "not the owner" decline (spam guard).
_DECLINED_AT: dict[int, float] = {}


def create_app() -> Flask:
    # static_folder=None disables Flask's built-in /static route, which would
    # otherwise shadow the Mini App's own asset route (it points at
    # app/static, a directory this project does not use). The dashboard serves
    # its assets from app/miniapp/static via the spa blueprint instead.
    app = Flask(__name__, static_folder=None)

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

    @app.get("/internal/cron")
    @app.post("/internal/cron")
    def internal_cron():
        """Secure endpoint for cron-job.org / GitHub Actions to trigger daily jobs (§16).

        Query params:
          secret=...  must match CRON_SECRET (defaults to WEBHOOK_SECRET)
          job=morning|notifications|daily|all  (default: daily)
          chat_id=... optional override
        """
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret") or ""
        expected = config.CRON_SECRET or config.WEBHOOK_SECRET
        if secret != expected:
            log.warning("cron.unauthorized", extra={"extra_fields": {}})
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        job = (request.args.get("job") or "daily").lower()
        chat_id = request.args.get("chat_id")
        try:
            chat_id = int(chat_id) if chat_id else None
        except ValueError:
            chat_id = None

        from app.automation.cron import run_morning_job, run_notifications_job, run_daily_jobs

        if job in ("morning", "report"):
            result = run_morning_job(chat_id=chat_id)
        elif job in ("notifications", "notify", "notif"):
            result = run_notifications_job(chat_id=chat_id)
        else:
            result = run_daily_jobs(chat_id=chat_id)

        return jsonify(result)

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
            # P0: approval buttons are owner-only too (cards always land in the
            # owner's chat; the gateway separately binds decisions to requester).
            _admins = config.admin_chat_ids()
            if _admins and cb.get("chat_id") not in _admins:
                if cb.get("callback_query_id"):
                    try:
                        answer_callback_query(cb["callback_query_id"], "شما مجاز به تأیید نیستید.")
                    except Exception:  # noqa: BLE001
                        pass
                return jsonify({"ok": True, "ignored": "not_owner"})
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

        # ── P0 security: ownership gate ─────────────────────────────────────
        # The webhook secret proves the update comes from Telegram, NOT that the
        # sender is Ali. Without this gate, any stranger who finds the bot could
        # read /dossier /crm /finance. Unknown chats get one polite decline/hour.
        # /whoami stays open so the owner can discover their chat id to configure
        # TELEGRAM_ADMIN_CHAT_ID (chicken-and-egg).
        admins = config.admin_chat_ids()
        text = parsed["text"].strip()
        if text.split()[0].lower().startswith("/whoami"):
            try:
                if admins:
                    lock_line = f"🔐 قفل مالکیت فعال است — {len(admins)} چت مجاز ثبت شده."
                    guide = ""
                else:
                    lock_line = "⚠️ قفل مالکیت غیرفعال است — بات فعلاً به همه پاسخ می‌دهد."
                    guide = "\n\nاین عدد را در env سرور به‌عنوان TELEGRAM_ADMIN_CHAT_ID ثبت کنید."
                send_message(
                    chat_id=parsed["chat_id"],
                    text=f"🆔 chat_id شما: `{parsed['chat_id']}`\n{lock_line}{guide}",
                )
            except Exception:  # noqa: BLE001
                pass
            return jsonify({"ok": True, "whoami": True, "owner_lock_enabled": bool(admins), "allowed_chats": len(admins)})

        if admins and parsed.get("chat_id") not in admins:
            log_event(
                log, "webhook.rejected",
                user_id=parsed["user_id"],
                payload={"chat_id": parsed["chat_id"], "text": text[:60]},
            )
            import time as _time
            now = _time.time()
            if now - _DECLINED_AT.get(parsed["chat_id"], 0) > 3600:
                _DECLINED_AT[parsed["chat_id"]] = now
                try:
                    send_message(chat_id=parsed["chat_id"], text="این بات شخصی است و فقط به مالکش پاسخ می‌دهد. 🤖")
                except Exception:  # noqa: BLE001
                    pass
            return jsonify({"ok": True, "ignored": "not_owner"})

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

    # ── Speed: gzip text responses ──────────────────────────────────────────
    # The Mini App is a ~170 KB inline SPA served by Flask; Render's free plan
    # does not compress origin responses. gzip cuts HTML/JSON transfer ~5x —
    # the difference between a crawling and an instant panel on slow links.
    import gzip as _gzip

    COMPRESSIBLE = ("text/", "application/json", "javascript", "image/svg+xml")

    @app.after_request
    def _compress_response(resp):
        try:
            accept_enc = request.headers.get("Accept-Encoding", "")
            if (
                "gzip" not in accept_enc.lower()
                or resp.status_code != 200
                or "Content-Encoding" in resp.headers
            ):
                return resp
            ctype = resp.headers.get("Content-Type", "")
            if not any(t in ctype for t in COMPRESSIBLE):
                return resp
            if resp.direct_passthrough:
                # send_from_directory responses stream the file; materialize it
                # once so we can compress (Werkzeug forbids get_data in this mode).
                body = b"".join(resp.response)
            else:
                body = resp.get_data()
            if not (860 <= len(body) <= 2_000_000):
                return resp
            if resp.direct_passthrough:
                resp = app.response_class(body, status=resp.status_code, headers=resp.headers)
            compressed = _gzip.compress(body, 6)
            if len(compressed) >= len(body) * 0.9:
                return resp
            resp.set_data(compressed)
            resp.headers["Content-Encoding"] = "gzip"
            resp.headers["Content-Length"] = str(len(compressed))
            resp.headers["Vary"] = "Accept-Encoding"
            # NB: Cache-Control is left untouched — the SPA route deliberately
            # sends no-store so Telegram's webview never shows a stale panel.
        except Exception as exc:  # noqa: BLE001 — compression must never break a response
            log.debug("compress.skip", extra={"extra_fields": {"error": f"{type(exc).__name__}: {exc}"}})
        return resp

    # P0: loud reminder when the ownership gate is not configured yet.
    if not config.admin_chat_ids():
        log.warning(
            "security.no_owner_gate",
            extra={"extra_fields": {"hint": "TELEGRAM_ADMIN_CHAT_ID unset — bot replies to ANYONE"}},
        )

    return app


app = create_app()
