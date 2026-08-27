"""Financial Agent — monthly income tracking with automated payment reminders (§15 redefined).

User's real need: each project has monthly contract, must pay monthly, different amounts,
tracking paid/unpaid per Jalali month is critical. When overdue, bot should send automated
reminder to client, clearly stating it's automated from Net Nova agency assistant, not personal.

Features:
- Generate payment reminder messages (automated tone)
- Send overdue reminders via Telegram (if client chat_id known) or Email (if SMTP) or to owner as fallback
- Approval-gated: sending to client is YELLOW (one approval)
- Integration with cron for automatic checks
"""

from __future__ import annotations

import time
from typing import Any

from app import db, repositories as repo
from app.crm.repository import list_contacts, get_contact_by_id
from app.financial.repository import list_incomes, monthly_summary, mark_overdue_if_needed, get_income
from app.logging_config import get_logger
from app.utils.jalali import fa_num, format_timestamp_fa

log = get_logger("financial_agent")

# Templates for payment reminders — must clearly state it's automated
REMINDER_TEMPLATES = {
    "first": """سلام {client_name} عزیز،

این پیام به صورت خودکار از طرف دستیار هوشمند آژانس نت نوا (Ali OS) ارسال شده است.

برای پروژه «{project_name}» مبلغ {amount} {currency} بابت ماه {month_jalali} هنوز پرداخت نشده است.

📅 موعد پرداخت: {due_date}
💰 مبلغ: {amount} {currency}

لطفاً در اولین فرصت نسبت به پرداخت اقدام فرمایید تا روند کاری پروژه بدون اختلال ادامه یابد.

با تشکر،
🤖 دستیار خودکار آژانس نت نوا
_این پیام به صورت خودکار ارسال شده و نیاز به پاسخ ندارد، اما در صورت سوال با علی در ارتباط باشید._
""",
    "overdue": """سلام {client_name} عزیز،

این یک یادآوری خودکار از طرف دستیار آژانس نت نوا (Ali OS) است.

پرداخت پروژه «{project_name}» بابت ماه {month_jalali} به مبلغ {amount} {currency} از موعد گذشته است.

⚠️ {days_overdue} روز از موعد پرداخت گذشته
📅 موعد: {due_date}
💰 مبلغ: {amount} {currency}

لطفاً هرچه سریع‌تر نسبت به تسویه اقدام فرمایید.

با احترام،
🤖 دستیار خودکار نت نوا — آژانس دیجیتال مارکتینگ
_این پیام خودکار است و توسط سیستم ارسال شده، نه به صورت شخصی از طرف علی._
""",
    "second_overdue": """سلام {client_name}،

این دومین یادآوری خودکار برای پرداخت معوق پروژه «{project_name}» است.

🔴 مبلغ {amount} {currency} بابت ماه {month_jalali} هنوز پرداخت نشده و {days_overdue} روز تاخیر دارد.

برای جلوگیری از توقف پروژه، لطفاً امروز پرداخت را انجام دهید.

ممنون از همکاری‌تون،
🤖 دستیار مالی خودکار نت نوا
""",
}


def _find_client_contact(project_id: int) -> dict | None:
    """Find best client contact for a project — from CRM contacts or project_people."""
    # Try CRM contacts with status customer/prospect
    try:
        contacts = list_contacts(project_id=project_id, limit=10)
        # Prefer customer, then prospect, then lead
        for status in ("customer", "prospect", "partner", "lead"):
            for c in contacts:
                if c["status"] == status:
                    return dict(c)
        if contacts:
            return dict(contacts[0])
    except Exception:
        pass

    # Try project_people where is_internal=0 (external)
    try:
        rows = db.query_all(
            "SELECT * FROM project_people WHERE project_id=? AND is_internal=0 ORDER BY id LIMIT 3",
            (project_id,),
        )
        if rows:
            # Convert to contact-like dict
            r = rows[0]
            return {
                "name": r["name"],
                "company": None,
                "email": r["contact"] if "@" in (r["contact"] or "") else None,
                "telegram_chat_id": r["telegram_chat_id"],
                "telegram": None,
                "project_id": project_id,
            }
    except Exception:
        pass

    return None


def generate_reminder_message(
    income_uid: str,
    *,
    template: str = "overdue",
) -> dict:
    """Generate reminder message for an income record."""
    income = get_income(income_uid)
    if not income:
        raise ValueError(f"Income not found: {income_uid}")

    project = repo.get_project(income["project_id"])
    project_name = project["name"] if project else f"پروژه {income['project_id']}"

    client = _find_client_contact(income["project_id"])
    client_name = client["name"] if client else "عزیز"

    # Days overdue
    now = time.time()
    due = income["due_at"] or now
    days_overdue = max(0, int((now - due) / 86400))

    # Due date formatted Jalali
    due_str = format_timestamp_fa(due) if due else income["month_jalali"]

    # Choose template
    if template not in REMINDER_TEMPLATES:
        template = "overdue" if days_overdue > 0 else "first"
        if days_overdue > 7:
            template = "second_overdue"

    tpl = REMINDER_TEMPLATES[template]

    amount = float(income["amount"] or 0)
    currency = income["currency"] or "تومان"
    # Format amount with Persian numbers? Keep comma + Persian
    amount_str = f"{amount:,.0f}"

    message = tpl.format(
        client_name=client_name,
        project_name=project_name,
        amount=amount_str,
        currency=currency,
        month_jalali=income["month_jalali"],
        due_date=due_str,
        days_overdue=fa_num(days_overdue),
    )

    return {
        "income": dict(income),
        "project": dict(project) if project else None,
        "client": client,
        "message": message,
        "days_overdue": days_overdue,
        "template_used": template,
    }


def send_overdue_reminders(
    *,
    project_id: int | None = None,
    dry_run: bool = True,
    max_send: int = 5,
) -> list[dict]:
    """Generate and optionally send overdue payment reminders.

    dry_run=True → only generate messages, don't actually send
    Returns list of results with message and send status.
    """
    mark_overdue_if_needed()
    overdue = list_incomes(status="overdue", project_id=project_id, limit=20)

    results = []

    for inc in overdue[:max_send]:
        try:
            reminder = generate_reminder_message(inc["income_uid"], template="overdue")
            client = reminder["client"]
            message = reminder["message"]

            send_result = {"sent": False, "method": None, "error": None}

            if not dry_run:
                # Try to send via Telegram to client if chat_id known
                from app import approvals

                # We need to send via approval gateway if sending to external client
                # For dry_run=False, we actually attempt to send via approval
                # The approval action will handle sending

                # Determine sending method
                if client and client.get("telegram_chat_id"):
                    # Direct Telegram to client — requires approval
                    try:
                        res = approvals.request_action(
                            action_type="financial.send_reminder",
                            title=f"یادآوری پرداخت به {client.get('name')} برای {reminder['project']['name'] if reminder['project'] else ''}",
                            summary=f"مبلغ {float(inc['amount']):,.0f} بابت {inc['month_jalali']} — {reminder['days_overdue']} روز معوق",
                            payload={
                                "income_uid": inc["income_uid"],
                                "client_telegram_chat_id": client["telegram_chat_id"],
                                "client_email": client.get("email"),
                                "message": message,
                                "project_id": inc["project_id"],
                            },
                            requested_by=None,
                            project_id=inc["project_id"],
                            agent="financial_agent",
                        )
                        send_result = {"sent": res.executed, "method": "telegram_client", "action_uid": res.action_uid, "message": res.message}
                    except Exception as exc:
                        send_result = {"sent": False, "method": "telegram_client", "error": str(exc)}

                elif client and client.get("email"):
                    # Try email if SMTP configured
                    try:
                        res = approvals.request_action(
                            action_type="financial.send_reminder",
                            title=f"یادآوری پرداخت ایمیلی به {client.get('name')}",
                            summary=f"مبلغ {float(inc['amount']):,.0f} بابت {inc['month_jalali']}",
                            payload={
                                "income_uid": inc["income_uid"],
                                "client_email": client["email"],
                                "message": message,
                                "project_id": inc["project_id"],
                            },
                            requested_by=None,
                            project_id=inc["project_id"],
                            agent="financial_agent",
                        )
                        send_result = {"sent": res.executed, "method": "email", "action_uid": res.action_uid}
                    except Exception as exc:
                        send_result = {"sent": False, "method": "email", "error": str(exc)}

                else:
                    # No direct client contact — send to owner as notification with message to forward
                    send_result = {"sent": False, "method": "no_client_contact", "error": "اطلاعات تماس کارفرما موجود نیست — پیام برای علی آماده شد"}

            results.append({
                "income_uid": inc["income_uid"],
                "project_id": inc["project_id"],
                "project_name": reminder["project"]["name"] if reminder["project"] else "",
                "client": client,
                "message": message,
                "days_overdue": reminder["days_overdue"],
                "send_result": send_result,
                "dry_run": dry_run,
            })

        except Exception as exc:
            log.exception("financial.reminder_failed", extra={"extra_fields": {"income_uid": inc["income_uid"]}})
            results.append({
                "income_uid": inc["income_uid"],
                "error": str(exc),
                "dry_run": dry_run,
            })

    return results


def format_overdue_summary_telegram(results: list[dict]) -> str:
    """Format overdue reminders summary for Telegram to owner."""
    if not results:
        return "✅ هیچ پرداخت معوقی نیست — همه واریزی‌ها مرتب است!"

    lines = [f"💰 *یادآوری پرداخت‌های معوق — {fa_num(len(results))} مورد*", ""]

    for r in results[:10]:
        if "error" in r and "income_uid" not in r:
            lines.append(f"⚠️ خطا: {r['error']}")
            continue

        proj = r.get("project_name") or f"پروژه {r.get('project_id')}"
        client = r.get("client", {})
        client_name = client.get("name") if client else "کارفرما"
        days = r.get("days_overdue", 0)
        inc_uid = r.get("income_uid", "")

        lines.append(f"🔴 {proj} — {client_name} — {fa_num(days)} روز معوق")
        lines.append(f"   `{inc_uid}`")
        if r.get("send_result"):
            sr = r["send_result"]
            if sr.get("sent"):
                lines.append(f"   ✅ ارسال شد via {sr.get('method')}")
            else:
                if sr.get("method") == "no_client_contact":
                    lines.append(f"   ⚠️ تماس کارفرما موجود نیست — پیام آماده برای فوروارد:")
                    # Include message preview
                    msg_preview = r.get("message", "")[:200]
                    lines.append(f"   _{msg_preview}..._")
                else:
                    lines.append(f"   ⏳ در انتظار تأیید: {sr.get('action_uid') or sr.get('error')}")

        lines.append("")

    lines.append("_برای ارسال خودکار به کارفرما، اطلاعات تلگرام/ایمیل او را در CRM ثبت کن._")
    return "\n".join(lines)
