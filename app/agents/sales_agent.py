"""Sales Agent (§13) — pipeline, followups, sales messages.

- Analyze deals pipeline
- Suggest next actions
- Generate sales follow-up messages
- Track deal velocity and risk
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from app import db, repositories as repo
from app.crm.repository import list_deals, upcoming_followups, crm_stats, get_contact
from app.utils.jalali import TEHRAN_TZ, fa_num, format_timestamp_fa


def analyze_sales_pipeline(*, project_id: int | None = None) -> dict:
    now = time.time()
    deals = list_deals(project_id=project_id, limit=200)
    stats = crm_stats(project_id=project_id)

    # Group by stage
    by_stage: dict[str, list] = {}
    for d in deals:
        by_stage.setdefault(d["stage"], []).append(d)

    # Calculate stage conversion (simple)
    stage_order = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]
    pipeline_value = 0.0
    weighted_value = 0.0  # value * probability

    for d in deals:
        if d["stage"] not in ("won", "lost"):
            amt = float(d["amount"] or 0)
            pipeline_value += amt
            weighted_value += amt * (d["probability"] or 50) / 100

    # Stale deals
    stale_deals = []
    for d in deals:
        if d["stage"] in ("won", "lost"):
            continue
        age = now - d["updated_at"]
        if age > 7 * 86400:  # 7 days
            stale_deals.append({**dict(d), "days_stale": int(age / 86400)})

    # Deals closing soon
    closing_soon = []
    for d in deals:
        if d["stage"] in ("won", "lost"):
            continue
        if d["expected_close_at"]:
            delta = d["expected_close_at"] - now
            if 0 <= delta <= 7 * 86400:
                closing_soon.append({**dict(d), "days_to_close": int(delta / 86400)})

    # Overdue followups linked to deals
    overdue_followups = upcoming_followups(project_id=project_id, overdue_only=True, limit=20)

    # Recommendations
    recommendations: list[str] = []
    if stale_deals:
        recommendations.append(f"{len(stale_deals)} معامله راکد است — پیگیری کن")
    if closing_soon:
        recommendations.append(f"{len(closing_soon)} معامله در ۷ روز آینده بسته می‌شود — آماده باش")
    if overdue_followups:
        recommendations.append(f"{len(overdue_followups)} پیگیری معوق — تماس بگیر")

    # Next actions per deal
    next_actions = []
    for d in deals:
        if d["stage"] == "lead":
            next_actions.append({"deal_uid": d["deal_uid"], "title": d["title"], "action": "تماس اولیه و نیازسنجی", "priority": "high"})
        elif d["stage"] == "qualified":
            next_actions.append({"deal_uid": d["deal_uid"], "title": d["title"], "action": "ارسال پیشنهاد و پیش‌فاکتور", "priority": "high"})
        elif d["stage"] == "proposal":
            next_actions.append({"deal_uid": d["deal_uid"], "title": d["title"], "action": "پیگیری پیشنهاد و پاسخ به سوالات", "priority": "medium"})
        elif d["stage"] == "negotiation":
            next_actions.append({"deal_uid": d["deal_uid"], "title": d["title"], "action": "مذاکره نهایی و بستن قرارداد", "priority": "high"})

    return {
        "generated_at": now,
        "project_id": project_id,
        "total_deals": len(deals),
        "by_stage": {k: len(v) for k, v in by_stage.items()},
        "by_stage_details": {k: [dict(x) for x in v[:10]] for k, v in by_stage.items()},
        "pipeline_value": pipeline_value,
        "weighted_value": weighted_value,
        "stats": stats,
        "stale_deals": stale_deals[:10],
        "closing_soon": closing_soon[:10],
        "overdue_followups": [dict(f) for f in overdue_followups[:10]],
        "next_actions": next_actions[:15],
        "recommendations": recommendations,
    }


def generate_followup_message(
    *,
    deal_uid: str | None = None,
    contact_uid: str | None = None,
    tone: str = "professional",
) -> str:
    """Generate a sales follow-up message using simple templates (future: LLM)."""
    contact = None
    deal = None

    if contact_uid:
        from app.crm.repository import get_contact as _get_contact
        contact = _get_contact(contact_uid)

    if deal_uid:
        from app.crm.repository import get_deal as _get_deal, get_contact_by_id as _get_contact_by_id, get_contact as _get_contact2
        deal = _get_deal(deal_uid)
        if deal and deal["contact_id"] and not contact:
            try:
                contact = _get_contact_by_id(int(deal["contact_id"]))
            except Exception:
                try:
                    # fallback: contact_id might be uid? try by uid
                    contact = _get_contact2(deal["contact_id"]) if isinstance(deal["contact_id"], str) else None
                except Exception:
                    pass

    contact_name = contact["name"] if contact else "عزیز"
    company = contact["company"] if contact and contact["company"] else ""
    deal_title = deal["title"] if deal else ""

    templates = {
        "professional": f"""سلام {contact_name} عزیز،

امیدوارم حالتون خوب باشه.

در مورد {deal_title or 'پروژه‌تون'} می‌خواستم پیگیری کنم — آیا سوالی هست که بتونم کمک کنم؟

{('در ' + company + ' ') if company else ''}ما آماده‌ایم تا قدم بعدی رو با هم برداریم.

منتظر پاسختون هستم.

با احترام،
علی — Net Nova""",
        "friendly": f"""سلام {contact_name} جان 👋

چطوری؟ در مورد {deal_title or 'صحبتمون'} یادت نره — من اینجام اگر چیزی لازم داشتی.

بزن بریم جلو 🚀

علی""",
        "urgent": f"""سلام {contact_name}،

برای {deal_title or 'پروژه'} زمان‌بندی کمی فشرده‌ست — اگر تا فردا نهایی کنیم، می‌تونیم تخفیف ویژه‌ای در نظر بگیریم.

خبر بده تا رزرو کنیم.

علی""",
    }

    return templates.get(tone, templates["professional"])


def prepare_followup_send(
    *,
    deal_uid: str | None = None,
    contact_uid: str | None = None,
    tone: str = "professional",
    dry_run: bool = True,
    requested_by: int | None = None,
    chat_id: int | None = None,
) -> dict:
    """Prepare (and optionally queue for approval) a follow-up message to the client's Telegram.

    Mirrors the `financial.send_reminder` pattern: nothing is ever sent directly —
    a YELLOW approval request is created and the executor sends it after Ali confirms.
    """
    from app.crm.repository import get_contact, get_deal, get_contact_by_id

    contact = None
    deal = None
    if contact_uid:
        contact = get_contact(contact_uid)
    if deal_uid:
        deal = get_deal(deal_uid)
        if deal and not contact:
            try:
                contact = get_contact_by_id(int(deal["contact_id"]))
            except (ValueError, TypeError):
                contact = get_contact(str(deal["contact_id"])) if deal.get("contact_id") else None
            if contact is None and deal.get("contact_id"):
                contact = get_contact(str(deal["contact_id"]))

    if not contact:
        return {"ok": False, "error": "مخاطب این دیل در CRM پیدا نشد — اول مخاطب رو ثبت کن"}

    chat_id_client = contact["telegram_chat_id"] if "telegram_chat_id" in contact.keys() else None
    message = generate_followup_message(deal_uid=deal_uid, contact_uid=contact_uid, tone=tone)

    result = {
        "ok": True,
        "dry_run": dry_run,
        "contact_name": contact["name"],
        "contact_uid": contact["contact_uid"],
        "deal_uid": deal["deal_uid"] if deal else None,
        "deal_title": deal["title"] if deal else None,
        "project_id": (deal["project_id"] if deal else None) or None,
        "client_telegram_chat_id": chat_id_client,
        "message": message,
    }
    if not chat_id_client:
        result["no_client_contact"] = True
        return result

    if dry_run:
        return result

    from app import approvals

    res = approvals.request_action(
        action_type="sales.send_followup",
        title=f"ارسال پیام پیگیری به {contact['name']}" + (f" — {deal['title']}" if deal else ""),
        summary=f"تُن: {tone} — ارسال به تلگرام مخاطب (chat id {chat_id_client})",
        payload={
            "message": message,
            "client_telegram_chat_id": chat_id_client,
            "contact_uid": contact["contact_uid"],
            "contact_id": contact["id"],
            "deal_uid": deal["deal_uid"] if deal else None,
            "project_id": result["project_id"],
            "tone": tone,
        },
        requested_by=requested_by,
        project_id=result["project_id"],
        # کارت تأیید باید به چت علی برود، هرگز به چت مشتری
        chat_id=chat_id,
        agent="sales_agent",
    )
    result["action_uid"] = getattr(res, "action_uid", None) or (
        res.get("action_uid") if isinstance(res, dict) else None
    )
    result["approval_requested"] = bool(result["action_uid"])
    return result


def format_sales_report_telegram(pipeline: dict) -> str:
    lines = [
        f"💼 *گزارش فروش — {fa_num(pipeline['total_deals'])} معامله در pipeline*",
        f"💰 ارزش کل: {pipeline['pipeline_value']:,.0f} IRT — ارزش وزنی: {pipeline['weighted_value']:,.0f} IRT",
        "",
        "*تفکیک مرحله:*",
    ]

    stage_labels = {
        "lead": "سرنخ",
        "qualified": "واجد شرایط",
        "proposal": "پیشنهاد",
        "negotiation": "مذاکره",
        "won": "برنده ✅",
        "lost": "باخته ❌",
    }

    for stage, count in pipeline["by_stage"].items():
        label = stage_labels.get(stage, stage)
        lines.append(f"  • {label}: {fa_num(count)}")

    if pipeline["stale_deals"]:
        lines.append(f"\n⚠️ *راکد ({fa_num(len(pipeline['stale_deals']))}):*")
        for d in pipeline["stale_deals"][:5]:
            lines.append(f"  • {d['title']} — {fa_num(d['days_stale'])} روز بدون به‌روزرسانی")

    if pipeline["closing_soon"]:
        lines.append(f"\n📅 *بستن در ۷ روز آینده ({fa_num(len(pipeline['closing_soon']))}):*")
        for d in pipeline["closing_soon"][:5]:
            lines.append(f"  • {d['title']} — {fa_num(d['days_to_close'])} روز دیگر")

    if pipeline["overdue_followups"]:
        lines.append(f"\n📞 *پیگیری معوق ({fa_num(len(pipeline['overdue_followups']))}):*")
        for f in pipeline["overdue_followups"][:5]:
            lines.append(f"  • {f['contact_name']} — {f['summary']}")

    if pipeline["next_actions"]:
        lines.append(f"\n🎯 *اقدام بعدی:*")
        for na in pipeline["next_actions"][:6]:
            lines.append(f"  • {na['title']}: {na['action']}")

    if pipeline["recommendations"]:
        lines.append(f"\n💡 *توصیه:*")
        for rec in pipeline["recommendations"][:4]:
            lines.append(f"  • {rec}")

    lines.append("\n_برای مدیریت کامل CRM → داشبورد → تب CRM_")
    return "\n".join(lines)
