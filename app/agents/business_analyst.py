"""Business Analyst Agent (§12) — تحلیل کسب‌وکار.

- تحلیل CRM، تسک‌ها، پروژه‌ها، بودجه، معاملات، محتوا، گوگل
- تولید insight و پیشنهاد اقدام
"""

from __future__ import annotations

import time
from typing import Any

from app import db, repositories as repo
from app.crm.repository import crm_stats, list_deals, upcoming_followups
from app.content.repository import content_stats
from app.miniapp.analytics import project_health, velocity, approvals_summary
from app.utils.jalali import fa_num


def analyze_business(*, project_id: int | None = None) -> dict:
    """Generate business analysis — no LLM needed for MVP, deterministic insights."""
    now = time.time()

    # Basic stats
    crm = crm_stats(project_id=project_id)
    content = content_stats(project_id=project_id)
    health = project_health()
    vel = velocity()
    appr = approvals_summary()

    if project_id:
        health = [h for h in health if h["id"] == project_id]

    # Tasks analysis
    open_tasks = repo.list_tasks(project_id=project_id, limit=200)
    overdue = [t for t in open_tasks if t["due_at"] and t["due_at"] < now]
    hot = [t for t in open_tasks if t["priority"] in ("urgent", "high")]

    # Deals analysis
    deals = list_deals(project_id=project_id, limit=100)
    deals_by_stage = crm.get("deals_by_stage", {})
    open_amount = crm.get("open_deals_amount", 0)
    won_amount = crm.get("won_amount", 0)

    # Followups
    overdue_followups = upcoming_followups(project_id=project_id, overdue_only=True, limit=20)

    # Budget analysis (if project_id)
    budget_insights = []
    if project_id:
        try:
            budget_rows = repo.list_budget(project_id)
            for b in budget_rows:
                planned = float(b["amount"] or 0)
                spent = float(b["spent"] or 0)
                if planned > 0 and spent / planned > 0.9:
                    budget_insights.append({
                        "type": "budget_high",
                        "label": b["label"],
                        "planned": planned,
                        "spent": spent,
                        "percent": round(spent / planned * 100) if planned else 0,
                    })
        except Exception:
            pass

    # Insights generation
    insights: list[dict] = []
    recommendations: list[str] = []

    # Overdue tasks insight
    if overdue:
        insights.append({
            "type": "overdue_tasks",
            "severity": "high" if len(overdue) > 5 else "medium",
            "title": f"{len(overdue)} تسک معوق",
            "detail": f"{len(overdue)} تسک از موعد گذشته — نیاز به رسیدگی فوری",
        })
        recommendations.append(f"ابتدا {min(3, len(overdue))} تسک معوق را تعیین تکلیف کن")

    # Hot tasks
    if hot:
        insights.append({
            "type": "hot_tasks",
            "severity": "medium",
            "title": f"{len(hot)} تسک فوری/مهم",
            "detail": "تسک‌های با اولویت بالا باز هستند",
        })

    # Velocity
    change = vel.get("change_percent")
    if change is not None:
        if change < -20:
            insights.append({
                "type": "velocity_down",
                "severity": "high",
                "title": f"کاهش سرعت {abs(change)}٪",
                "detail": f"این هفته {vel.get('done_this_week',0)} انجام‌شده در مقابل {vel.get('done_last_week',0)} هفته قبل",
            })
            recommendations.append("دلیل کاهش سرعت را بررسی کن — تسک‌های مسدود یا کمبود منابع؟")
        elif change > 30:
            insights.append({
                "type": "velocity_up",
                "severity": "low",
                "title": f"افزایش سرعت {change}٪ 🚀",
                "detail": "روند خوبی داری — همین را حفظ کن",
            })

    # CRM insights
    if crm.get("contacts_total", 0) == 0:
        insights.append({
            "type": "crm_empty",
            "severity": "low",
            "title": "CRM خالی است",
            "detail": "هنوز مخاطبی ثبت نشده — فرصت برای شروع",
        })
        recommendations.append("اولین مخاطبان را از طریق /crm اضافه کن")

    if overdue_followups:
        insights.append({
            "type": "crm_overdue",
            "severity": "medium",
            "title": f"{len(overdue_followups)} پیگیری CRM معوق",
            "detail": "پیگیری‌های مخاطبان از موعد گذشته",
        })
        recommendations.append("پیگیری‌های معوق CRM را تماس بگیر")

    # Deals pipeline
    if deals:
        # Check for stale deals (no update in 14 days)
        stale = []
        for d in deals:
            age = now - d["updated_at"]
            if age > 14 * 86400 and d["stage"] not in ("won", "lost"):
                stale.append(d)
        if stale:
            insights.append({
                "type": "stale_deals",
                "severity": "medium",
                "title": f"{len(stale)} معامله راکد (۱۴+ روز بدون به‌روزرسانی)",
                "detail": "معاملات در مراحل میانی گیر کرده‌اند",
            })
            recommendations.append("معاملات راکد را پیگیری یا مرحله را به‌روزرسانی کن")

        # Won vs lost
        won = deals_by_stage.get("won", 0)
        lost = deals_by_stage.get("lost", 0)
        if won + lost > 0:
            win_rate = won / (won + lost) * 100
            insights.append({
                "type": "win_rate",
                "severity": "low" if win_rate >= 50 else "medium",
                "title": f"نرخ برد {win_rate:.0f}٪ (برد {won} / باخت {lost})",
                "detail": f"مجموع معاملات بسته‌شده: {won+lost}",
            })

        # High value open deals
        high_value = [d for d in deals if float(d["amount"] or 0) > 100_000_000 and d["stage"] not in ("won", "lost")]
        if high_value:
            insights.append({
                "type": "high_value_deals",
                "severity": "low",
                "title": f"{len(high_value)} معامله با ارزش بالا باز است",
                "detail": f"مجموع {sum(float(d['amount'] or 0) for d in high_value):,.0f} IRT در pipeline",
            })

    # Content insights
    if content.get("total", 0) > 0:
        draft_count = content.get("by_status", {}).get("draft", 0)
        pending = content.get("by_status", {}).get("pending_approval", 0)
        if draft_count > 5:
            insights.append({
                "type": "content_drafts_many",
                "severity": "low",
                "title": f"{draft_count} پیش‌نویس محتوا منتشرنشده",
                "detail": "محتواهای آماده انتشار دارند",
            })
            recommendations.append("پیش‌نویس‌های محتوا را بررسی و به وردپرس بفرست")
        if pending:
            insights.append({
                "type": "content_pending",
                "severity": "medium",
                "title": f"{pending} محتوا منتظر تأیید",
                "detail": "محتواهای تولیدشده نیاز به تأیید تو دارند",
            })

    # Budget
    for b in budget_insights:
        insights.append({
            "type": "budget",
            "severity": "high" if b["percent"] > 100 else "medium",
            "title": f"بودجه «{b['label']}» {b['percent']}٪ مصرف شده",
            "detail": f"برنامه {b['planned']:,.0f} — هزینه {b['spent']:,.0f}",
        })

    # Approvals
    if appr.get("pending", 0) > 5:
        insights.append({
            "type": "approvals_many",
            "severity": "medium",
            "title": f"{appr['pending']} اقدام در صف تأیید",
            "detail": "صف تأیید شلوغ است",
        })
        recommendations.append("صف تأیید را خلوت کن — /approvals")

    # Project health
    for p in health:
        if p["completion"] is not None and p["completion"] < 30 and p["open_tasks"] > 5:
            insights.append({
                "type": "project_low_completion",
                "severity": "medium",
                "title": f"پروژه {p['name']} پیشرفت کم ({p['completion']}٪)",
                "detail": f"{p['open_tasks']} تسک باز، {p['hot_tasks']} فوری",
            })

    # Overall health score (0-100)
    # Start at 100, deduct for issues
    health_score = 100
    for ins in insights:
        if ins["severity"] == "high":
            health_score -= 15
        elif ins["severity"] == "medium":
            health_score -= 7
        elif ins["severity"] == "low":
            health_score -= 2
    health_score = max(0, min(100, health_score))

    return {
        "generated_at": now,
        "project_id": project_id,
        "health_score": health_score,
        "health_label": "عالی" if health_score >= 85 else "خوب" if health_score >= 70 else "متوسط" if health_score >= 50 else "نیاز به توجه",
        "counts": {
            "open_tasks": len(open_tasks),
            "overdue_tasks": len(overdue),
            "hot_tasks": len(hot),
            "deals_total": len(deals),
            "overdue_followups": len(overdue_followups),
        },
        "crm": crm,
        "content": content,
        "velocity": vel,
        "approvals": appr,
        "project_health": health,
        "insights": insights,
        "recommendations": recommendations[:8],
        "budget_insights": budget_insights,
    }


def format_business_report_telegram(analysis: dict) -> str:
    """Format as Telegram message."""
    score = analysis["health_score"]
    label = analysis["health_label"]
    counts = analysis["counts"]

    lines = [
        f"📊 *تحلیل کسب‌وکار — امتیاز سلامت {fa_num(score)}٪ ({label})*",
        "",
        f"📋 {fa_num(counts['open_tasks'])} تسک باز، {fa_num(counts['overdue_tasks'])} معوق، {fa_num(counts['hot_tasks'])} فوری",
        f"💼 {fa_num(counts['deals_total'])} معامله، {fa_num(counts['overdue_followups'])} پیگیری معوق CRM",
        "",
    ]

    if analysis["insights"]:
        lines.append("🔍 *یافته‌ها:*")
        for ins in analysis["insights"][:8]:
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(ins["severity"], "•")
            lines.append(f"{emoji} {ins['title']}")
            if ins.get("detail"):
                lines.append(f"   {ins['detail']}")
        lines.append("")

    if analysis["recommendations"]:
        lines.append("💡 *پیشنهاد اقدام:*")
        for i, rec in enumerate(analysis["recommendations"][:5], 1):
            lines.append(f"  {fa_num(i)}. {rec}")
        lines.append("")

    # CRM summary
    crm = analysis.get("crm", {})
    if crm:
        lines.append(f"👥 CRM: {fa_num(crm.get('contacts_total',0))} مخاطب، {fa_num(crm.get('deals_total',0))} معامله")
        if crm.get("open_deals_amount"):
            lines.append(f"   Pipeline: {crm['open_deals_amount']:,.0f} IRT باز")

    lines.append("\n_برای جزئیات داشبورد را باز کن._")
    return "\n".join(lines)
