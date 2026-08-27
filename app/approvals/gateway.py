"""Approval gateway — the single door every side-effecting action goes through.

Flow:

    agent → request_action(...)
        risk 🟢 → executed immediately, recorded as `executed`
        risk 🟡 → pending_actions row + Telegram card with [✅ تأیید] [❌ لغو]
        risk 🔴 → same, but the first ✅ moves it to `confirming` and a second
                  ✅ (a different button payload) is needed before execution

    Ali presses a button → webhook → handle_callback(...) → approve()/reject()
        approve() runs the registered executor and rewrites the card with the
        outcome, so the chat itself is the audit UI.

Nothing here talks to the LLM; it is deterministic, testable business logic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app import repositories as repo
from app.approvals import risk as risk_mod
from app.approvals.registry import UnknownAction, run as run_executor
from app.logging_config import get_logger, log_event

log = get_logger("approvals")

CB_PREFIX = "ap"          # callback_data namespace
CB_APPROVE = "ok"
CB_REJECT = "no"
CB_CONFIRM = "ok2"        # second step for 🔴
CB_DETAILS = "info"


@dataclass
class ActionResult:
    """What the caller gets back from request_action()."""
    action_uid: str
    status: str            # executed | pending | failed
    risk: str
    executed: bool
    result: Any = None
    error: str | None = None
    message: str = ""


# ── callback_data helpers ───────────────────────────────────────────────────

def make_callback(kind: str, action_uid: str) -> str:
    return f"{CB_PREFIX}:{kind}:{action_uid}"


def parse_callback(data: str) -> tuple[str, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != CB_PREFIX:
        return None
    return parts[1], parts[2]


def is_approval_callback(data: str) -> bool:
    return (data or "").startswith(f"{CB_PREFIX}:")


# ── Rendering ───────────────────────────────────────────────────────────────

def render_card(action: Any, *, footer: str | None = None) -> str:
    emoji = risk_mod.EMOJI.get(action["risk"], "🟡")
    label = risk_mod.LABEL_FA.get(action["risk"], "نیازمند تأیید")
    lines = [f"{emoji} *درخواست تأیید* — {label}", "", f"*{action['title']}*"]
    if action["summary"]:
        lines.append(action["summary"])
    project_name = None
    try:
        project_name = action["project_name"]
    except Exception:  # noqa: BLE001 — row without the join
        project_name = None
    if project_name:
        lines.append(f"📂 پروژه: {project_name}")
    lines.append(f"⚙️ عملیات: `{action['action_type']}`")

    payload = repo.action_payload(action)
    if payload:
        preview = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(preview) > 600:
            preview = preview[:600] + "\n…"
        lines.append(f"\n📦 جزئیات:\n```\n{preview}\n```")

    is_open = action["status"] in ("pending", "confirming")
    if action["risk"] == risk_mod.RED:
        required = int(action["approvals_required"] or 2)
        if is_open:
            # The step Ali is being asked for right now, never beyond the max.
            step = min(int(action["approvals_count"] or 0) + 1, required)
            lines.append(f"\n⚠️ این اقدام برگشت‌ناپذیر است — تأیید مرحله {step} از {required}.")
        else:
            lines.append("\n⚠️ اقدام برگشت‌ناپذیر (تأیید دو مرحله‌ای).")
    # A countdown only makes sense while the card is still actionable.
    if is_open and action["expires_at"]:
        mins = max(0, int((action["expires_at"] - repo.db.now()) / 60))
        lines.append(f"⏳ اعتبار: {mins} دقیقه دیگر")
    lines.append(f"\n🔖 `{action['action_uid']}`")
    if footer:
        lines.append(f"\n{footer}")
    return "\n".join(lines)


def build_keyboard(action: Any) -> dict:
    from app.telegram import button, inline_keyboard

    uid = action["action_uid"]
    if action["status"] == "confirming":
        approve_btn = button("⚠️ تأیید نهایی", make_callback(CB_CONFIRM, uid))
    else:
        approve_btn = button("✅ تأیید", make_callback(CB_APPROVE, uid))
    return inline_keyboard([[
        approve_btn,
        button("❌ لغو", make_callback(CB_REJECT, uid)),
    ]])


# ── Public API for agents ───────────────────────────────────────────────────

def request_action(
    *,
    action_type: str,
    title: str,
    payload: dict | None = None,
    summary: str | None = None,
    requested_by: int | None = None,
    project_id: int | None = None,
    chat_id: int | None = None,
    agent: str = "master",
    notify: bool = True,
    force_risk: str | None = None,
) -> ActionResult:
    """Entry point for every agent action with a side effect."""
    level = force_risk if force_risk in risk_mod.EMOJI else risk_mod.classify(action_type)
    ttl = risk_mod.ttl_for(level)

    if risk_mod.is_auto(level):
        action = repo.create_pending_action(
            action_type=action_type, title=title, risk=level, summary=summary,
            payload=payload, requested_by=requested_by, project_id=project_id,
            agent=agent, chat_id=chat_id, approvals_required=1,
            ttl_seconds=ttl, status="approved",
        )
        return _execute(action, decided_by=requested_by, auto=True)

    action = repo.create_pending_action(
        action_type=action_type, title=title, risk=level, summary=summary,
        payload=payload, requested_by=requested_by, project_id=project_id,
        agent=agent, chat_id=chat_id,
        approvals_required=risk_mod.approvals_required(level),
        ttl_seconds=ttl, status="pending",
    )
    repo.record_event(
        "approval_requested", user_id=requested_by, project_id=project_id,
        payload={"action_uid": action["action_uid"], "type": action_type, "risk": level},
    )
    log_event(log, "approval.requested", action_uid=action["action_uid"],
              action_type=action_type, risk=level)

    if notify and chat_id:
        _send_card(action)
        action = repo.get_pending_action(action["action_uid"])

    return ActionResult(
        action_uid=action["action_uid"], status="pending", risk=level,
        executed=False,
        message=(f"{risk_mod.EMOJI[level]} این اقدام نیاز به تأیید تو دارد. "
                 "کارت تأیید را در چت بفرست‌شده می‌بینی."),
    )


def _send_card(action: Any) -> None:
    from app.telegram import send_message

    try:
        sent = send_message(
            chat_id=action["chat_id"],
            text=render_card(action),
            reply_markup=build_keyboard(action),
        )
        if sent.get("message_id"):
            repo.update_pending_action(action["action_uid"], message_id=sent["message_id"])
    except Exception as exc:  # noqa: BLE001 — never break the caller
        log.warning("approval.card_failed",
                    extra={"extra_fields": {"error": str(exc),
                                            "action_uid": action["action_uid"]}})


# ── Execution ───────────────────────────────────────────────────────────────

def _execute(action: Any, *, decided_by: int | None, auto: bool = False) -> ActionResult:
    uid = action["action_uid"]
    payload = repo.action_payload(action)
    ctx = {
        "action_uid": uid,
        "requested_by": action["requested_by"],
        "project_id": action["project_id"],
        "chat_id": action["chat_id"],
        "auto": auto,
    }
    try:
        result = run_executor(action["action_type"], payload, ctx)
    except UnknownAction as exc:
        repo.update_pending_action(uid, status="failed", error=str(exc),
                                   decided_by=decided_by, decided_at=repo.db.now())
        log.warning("approval.no_executor",
                    extra={"extra_fields": {"action_uid": uid,
                                            "action_type": action["action_type"]}})
        return ActionResult(uid, "failed", action["risk"], False, error=str(exc),
                            message="⚠️ برای این نوع عملیات هنوز اجراکننده‌ای ثبت نشده است.")
    except Exception as exc:  # noqa: BLE001
        repo.update_pending_action(uid, status="failed", error=f"{type(exc).__name__}: {exc}",
                                   decided_by=decided_by, decided_at=repo.db.now())
        log.exception("approval.execute_failed", extra={"extra_fields": {"action_uid": uid}})
        return ActionResult(uid, "failed", action["risk"], False, error=str(exc),
                            message=f"⚠️ اجرای عملیات با خطا مواجه شد: {type(exc).__name__}")

    repo.update_pending_action(
        uid, status="executed", decided_by=decided_by, decided_at=repo.db.now(),
        result_json=_safe_json(result),
    )
    repo.record_event(
        "action_executed", user_id=decided_by, project_id=action["project_id"],
        payload={"action_uid": uid, "type": action["action_type"], "auto": auto},
    )
    log_event(log, "approval.executed", action_uid=uid,
              action_type=action["action_type"], auto=auto)
    return ActionResult(uid, "executed", action["risk"], True, result=result,
                        message="✅ عملیات اجرا شد.")


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:4000]
    except Exception:  # noqa: BLE001
        return json.dumps({"repr": str(value)[:500]}, ensure_ascii=False)


# ── Decisions (called from the webhook callback handler) ────────────────────

class DecisionError(RuntimeError):
    """Raised when a button press is not acceptable (expired, foreign, done)."""


def _load_open(action_uid: str, user_id: int) -> Any:
    action = repo.get_pending_action(action_uid)
    if action is None:
        raise DecisionError("این درخواست پیدا نشد.")
    # Only the requester (or the owner who requested nothing) may decide.
    requester = action["requested_by"]
    if requester is not None:
        user = repo.get_user(user_id)
        if user is None or user["id"] != requester:
            raise DecisionError("این درخواست متعلق به تو نیست.")
    if action["status"] in ("executed", "approved"):
        raise DecisionError("این درخواست قبلاً تأیید و اجرا شده است.")
    if action["status"] == "rejected":
        raise DecisionError("این درخواست قبلاً لغو شده است.")
    if action["status"] == "expired":
        raise DecisionError("مهلت این درخواست تمام شده است.")
    if action["expires_at"] and action["expires_at"] < repo.db.now():
        repo.update_pending_action(action_uid, status="expired")
        raise DecisionError("مهلت این درخواست تمام شده است.")
    return action


def approve(action_uid: str, user_id: int) -> tuple[Any, ActionResult | None, str]:
    """Register one approval. Returns (action, result_or_None, toast_text)."""
    action = _load_open(action_uid, user_id)
    user = repo.get_user(user_id)
    decided_by = user["id"] if user else None

    count = int(action["approvals_count"] or 0) + 1
    required = int(action["approvals_required"] or 1)

    if count < required:
        repo.update_pending_action(action_uid, approvals_count=count, status="confirming")
        repo.record_event("approval_step", user_id=decided_by,
                          project_id=action["project_id"],
                          payload={"action_uid": action_uid, "step": count, "of": required})
        updated = repo.get_pending_action(action_uid)
        return updated, None, f"مرحله {count} از {required} تأیید شد — تأیید نهایی لازم است."

    repo.update_pending_action(action_uid, approvals_count=count, status="approved")
    fresh = repo.get_pending_action(action_uid)
    result = _execute(fresh, decided_by=decided_by)
    return repo.get_pending_action(action_uid), result, (
        "✅ اجرا شد." if result.executed else "⚠️ اجرا ناموفق بود."
    )


def reject(action_uid: str, user_id: int) -> tuple[Any, str]:
    action = _load_open(action_uid, user_id)
    user = repo.get_user(user_id)
    repo.update_pending_action(
        action_uid, status="rejected",
        decided_by=user["id"] if user else None, decided_at=repo.db.now(),
    )
    repo.record_event("approval_rejected", user_id=user["id"] if user else None,
                      project_id=action["project_id"],
                      payload={"action_uid": action_uid, "type": action["action_type"]})
    log_event(log, "approval.rejected", action_uid=action_uid)
    return repo.get_pending_action(action_uid), "❌ لغو شد."


def final_text(action: Any, result: ActionResult | None) -> str:
    """The frozen card shown after a decision."""
    status = action["status"]
    if status == "executed":
        footer = "✅ *تأیید و اجرا شد.*"
        if result is not None and result.result is not None:
            summary = str(result.result)
            if len(summary) > 300:
                summary = summary[:300] + "…"
            footer += f"\nنتیجه: {summary}"
    elif status == "rejected":
        footer = "❌ *لغو شد — هیچ تغییری اعمال نشد.*"
    elif status == "failed":
        footer = f"⚠️ *اجرا با خطا متوقف شد:* {action['error'] or 'نامشخص'}"
    elif status == "expired":
        footer = "⏳ *مهلت تأیید تمام شد.*"
    elif status == "confirming":
        footer = ("⚠️ *مرحله اول تأیید ثبت شد.* برای اجرای این اقدام برگشت‌ناپذیر، "
                  "تأیید نهایی را بزن.")
    else:
        footer = "⏳ در انتظار تصمیم."
    return render_card(action, footer=footer)


# ── Telegram callback entry point ───────────────────────────────────────────

def _toast(cq_id: str | None, text: str, *, alert: bool = False) -> None:
    """Answer a callback query, never letting a network hiccup bubble up.

    Telegram gives us ~seconds to answer; if that call fails the button just
    keeps spinning on the client, which must not abort the decision we already
    committed to the database.
    """
    if not cq_id:
        return
    from app.telegram import answer_callback_query
    try:
        answer_callback_query(cq_id, text, show_alert=alert)
    except Exception as exc:  # noqa: BLE001
        log.warning("approval.answer_failed", extra={"extra_fields": {"error": str(exc)}})


def handle_callback(cb: dict) -> None:
    """Handle an inline-button press on an approval card."""
    from app.telegram import edit_message_text

    parsed = parse_callback(cb.get("data", ""))
    cq_id = cb.get("callback_query_id")
    if not parsed:
        _toast(cq_id, "دکمه نامعتبر است.")
        return
    kind, action_uid = parsed
    user_id = cb.get("user_id")

    try:
        if kind in (CB_APPROVE, CB_CONFIRM):
            action, result, toast = approve(action_uid, user_id)
        elif kind == CB_REJECT:
            action, toast = reject(action_uid, user_id)
            result = None
        elif kind == CB_DETAILS:
            _toast(cq_id, "جزئیات در همان پیام است.")
            return
        else:
            _toast(cq_id, "عملیات ناشناخته.")
            return
    except DecisionError as exc:
        _toast(cq_id, str(exc), alert=True)
        # Clean stale buttons off the card so it can't be pressed again.
        stale = repo.get_pending_action(action_uid)
        if stale is not None and cb.get("chat_id") and cb.get("message_id"):
            try:
                edit_message_text(cb["chat_id"], cb["message_id"],
                                  final_text(stale, None), reply_markup=None)
            except Exception:  # noqa: BLE001
                pass
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("approval.callback_error",
                      extra={"extra_fields": {"error": str(exc), "action_uid": action_uid}})
        _toast(cq_id, "خطای داخلی رخ داد.", alert=True)
        return

    _toast(cq_id, toast)

    chat_id = action["chat_id"] or cb.get("chat_id")
    message_id = action["message_id"] or cb.get("message_id")
    if chat_id and message_id:
        keyboard = build_keyboard(action) if action["status"] == "confirming" else None
        try:
            edit_message_text(chat_id, message_id, final_text(action, result),
                              reply_markup=keyboard)
        except Exception as exc:  # noqa: BLE001
            log.warning("approval.edit_failed", extra={"extra_fields": {"error": str(exc)}})
