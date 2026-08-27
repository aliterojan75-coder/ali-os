"""PM Agent — Morning report, smart prioritization, Jalali calendar.

Responsibilities (§11):
- Generate morning report with Jalali date
- Smart prioritization of tasks (urgency, due date, project health, approvals)
- Provide data for /morning command and dashboard popup
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app import db, repositories as repo
from app.crm import repository as crm_repo
from app.utils.jalali import (
    TEHRAN_TZ,
    format_jalali,
    gregorian_to_jalali,
    today_jalali,
    timestamp_to_jalali,
    format_timestamp_fa,
    jalali_today_str,
    fa_num,
)

# ── Prioritization ───────────────────────────────────────────────────────────

PRIORITY_WEIGHT = {"urgent": 100, "high": 70, "normal": 30, "low": 10}
STATUS_WEIGHT = {
    "inbox": 20,
    "planned": 15,
    "in_progress": 25,
    "blocked": 5,
    "waiting_approval": 10,
}


def score_task(task: Any, now_ts: float | None = None) -> float:
    """Calculate priority score for a task — higher means more urgent."""
    now = now_ts or time.time()
    score = 0.0

    # Base priority
    score += PRIORITY_WEIGHT.get(task["priority"], 30)
    score += STATUS_WEIGHT.get(task["status"], 10)

    # Due date handling
    due = task["due_at"]
    if due is not None:
        delta = due - now
        if delta < 0:
            # Overdue — heavy penalty, grows with days overdue
            overdue_days = abs(delta) / 86400
            score += 50 + min(overdue_days * 10, 50)  # up to +100
        elif delta < 86400:
            # Due today
            score += 35
        elif delta < 2 * 86400:
            # Due tomorrow
            score += 20
        elif delta < 7 * 86400:
            # Due this week
            score += 10

    # Hot project boost (if project has many hot tasks, slightly boost)
    # We don't have project health here, but we can check if project exists
    # and give a small boost for active projects.

    # Age boost: older tasks that are still open get slight boost (to avoid stale)
    age_days = (now - task["created_at"]) / 86400
    if age_days > 7:
        score += min(age_days, 20)

    return score


def prioritized_tasks(
    *,
    project_id: int | None = None,
    limit: int = 20,
    now_ts: float | None = None,
) -> list[dict]:
    """Return open tasks sorted by smart priority score."""
    tasks = repo.list_tasks(project_id=project_id, limit=200)
    now = now_ts or time.time()
    scored = []
    for t in tasks:
        s = score_task(t, now_ts=now)
        scored.append((s, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    result = []
    for score, task in scored[:limit]:
        d = dict(task)
        d["_priority_score"] = round(score, 1)
        # Add jalali due date if exists
        if d.get("due_at"):
            try:
                jy, jm, jd = timestamp_to_jalali(d["due_at"])
                d["_due_jalali"] = format_jalali(jy, jm, jd, with_weekday=False)
                d["_due_fa"] = format_timestamp_fa(d["due_at"])
            except Exception:
                d["_due_jalali"] = None
        result.append(d)
    return result


# ── Morning Report ───────────────────────────────────────────────────────────

def generate_morning_report(
    *,
    user_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """Generate full morning report data structure."""
    now_ts = time.time()
    now_dt = datetime.fromtimestamp(now_ts, TEHRAN_TZ)
    jy, jm, jd = today_jalali()
    from app.utils.jalali import JALALI_WEEKDAYS, jalali_weekday, JALALI_MONTHS

    wd_idx = jalali_weekday(jy, jm, jd)
    weekday_fa = JALALI_WEEKDAYS[wd_idx]

    # Date strings
    jalali_str = format_jalali(jy, jm, jd, with_weekday=True)
    gregorian_str = now_dt.strftime("%Y-%m-%d")

    # Tasks
    all_open = repo.list_tasks(project_id=project_id, limit=200)

    overdue = []
    due_today = []
    due_tomorrow = []
    hot = []

    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    tomorrow_start = today_start + 86400
    day_after = tomorrow_start + 86400

    for t in all_open:
        td = dict(t)
        due = t["due_at"]
        if due is not None:
            if due < now_ts:
                overdue.append(td)
            elif today_start <= due < tomorrow_start:
                due_today.append(td)
            elif tomorrow_start <= due < day_after:
                due_tomorrow.append(td)
        if t["priority"] in ("urgent", "high"):
            hot.append(td)

    # Prioritized list
    prioritized = prioritized_tasks(project_id=project_id, limit=15, now_ts=now_ts)

    # Approvals
    pending_approvals = [dict(a) for a in repo.list_pending_actions(limit=15)]
    expiring_approvals = []
    for a in pending_approvals:
        if a.get("expires_at") and a["expires_at"] - now_ts < 2 * 3600:  # <2h
            expiring_approvals.append(a)

    # CRM followups
    try:
        crm_followups = [dict(r) for r in crm_repo.upcoming_followups(project_id=project_id, within_days=3, limit=15)]
        overdue_followups = [dict(r) for r in crm_repo.upcoming_followups(project_id=project_id, overdue_only=True, limit=15)]
    except Exception:
        crm_followups = []
        overdue_followups = []

    # Project health
    try:
        from app.miniapp.analytics import project_health, velocity, approvals_summary
        health = project_health()
        vel = velocity()
        appr_summary = approvals_summary()
    except Exception:
        health = []
        vel = {}
        appr_summary = {}

    # CRM stats
    try:
        crm_stats = crm_repo.crm_stats(project_id=project_id)
    except Exception:
        crm_stats = {}

    # Counts
    counts = {
        "open_tasks": len(all_open),
        "overdue_tasks": len(overdue),
        "due_today": len(due_today),
        "due_tomorrow": len(due_tomorrow),
        "hot_tasks": len(hot),
        "pending_approvals": len(pending_approvals),
        "expiring_approvals": len(expiring_approvals),
        "crm_followups": len(crm_followups),
        "crm_overdue": len(overdue_followups),
    }

    return {
        "generated_at": now_ts,
        "generated_at_jalali": jalali_str,
        "date": {
            "gregorian": gregorian_str,
            "jalali": {"year": jy, "month": jm, "day": jd, "month_name": JALALI_MONTHS[jm - 1], "weekday": weekday_fa},
            "jalali_str": jalali_str,
            "weekday_fa": weekday_fa,
            "tehran_time": now_dt.strftime("%H:%M"),
        },
        "counts": counts,
        "overdue_tasks": overdue[:10],
        "due_today": due_today[:10],
        "due_tomorrow": due_tomorrow[:10],
        "hot_tasks": hot[:10],
        "prioritized_tasks": prioritized,
        "pending_approvals": pending_approvals[:10],
        "expiring_approvals": expiring_approvals,
        "crm_followups": crm_followups,
        "crm_overdue": overdue_followups,
        "project_health": health[:8],
        "velocity": vel,
        "approvals_summary": appr_summary,
        "crm_stats": crm_stats,
    }


def format_morning_report_telegram(report: dict) -> str:
    """Format morning report as Telegram Markdown text."""
    date = report["date"]
    counts = report["counts"]

    lines = [
        f"🌅 *گزارش صبحگاهی — {date['jalali_str']}*",
        f"🕐 {date['tehran_time']} به وقت تهران | {date['gregorian']} میلادی",
        "",
        f"📊 *خلاصه:* {fa_num(counts['open_tasks'])} تسک باز، {fa_num(counts['overdue_tasks'])} معوق، "
        f"{fa_num(counts['hot_tasks'])} فوری، {fa_num(counts['pending_approvals'])} در صف تأیید",
        "",
    ]

    if report["overdue_tasks"]:
        lines.append(f"⚠️ *معوق ({fa_num(len(report['overdue_tasks']))}):*")
        for t in report["overdue_tasks"][:5]:
            proj = f"[{t.get('project_name')}] " if t.get("project_name") else ""
            lines.append(f"  • {proj}{t['title']} — {t['priority']}")
        lines.append("")

    if report["due_today"]:
        lines.append(f"📅 *امروز ({fa_num(len(report['due_today']))}):*")
        for t in report["due_today"][:5]:
            proj = f"[{t.get('project_name')}] " if t.get("project_name") else ""
            lines.append(f"  • {proj}{t['title']}")
        lines.append("")

    if report["hot_tasks"]:
        lines.append(f"🔥 *فوری/مهم ({fa_num(len(report['hot_tasks']))}):*")
        for t in report["hot_tasks"][:5]:
            proj = f"[{t.get('project_name')}] " if t.get("project_name") else ""
            lines.append(f"  • {proj}{t['title']}")
        lines.append("")

    if report["prioritized_tasks"]:
        lines.append("🎯 *اولویت‌بندی هوشمند (۵ تای اول):*")
        for i, t in enumerate(report["prioritized_tasks"][:5], 1):
            proj = f"[{t.get('project_name')}] " if t.get("project_name") else ""
            score = t.get("_priority_score", "")
            lines.append(f"  {fa_num(i)}. {proj}{t['title']} — امتیاز {fa_num(score)}")
        lines.append("")

    if report["pending_approvals"]:
        lines.append(f"🔐 *صف تأیید ({fa_num(len(report['pending_approvals']))}):*")
        for a in report["pending_approvals"][:5]:
            lines.append(f"  • {a['title']} — {a['risk']}")
        lines.append("")

    if report["crm_overdue"]:
        lines.append(f"👥 *پیگیری CRM معوق ({fa_num(len(report['crm_overdue']))}):*")
        for f in report["crm_overdue"][:5]:
            lines.append(f"  • {f['contact_name']} — {f['summary']}")
        lines.append("")

    if report["crm_followups"]:
        lines.append(f"📞 *پیگیری‌های پیش رو ({fa_num(len(report['crm_followups']))}):*")
        for f in report["crm_followups"][:5]:
            lines.append(f"  • {f['contact_name']} — {f['summary']}")
        lines.append("")

    # Velocity
    vel = report.get("velocity", {})
    if vel:
        change = vel.get("change_percent")
        if change is not None:
            if change > 0:
                lines.append(f"📈 سرعت این هفته {fa_num(change)}٪ بیشتر از هفته قبل.")
            elif change < 0:
                lines.append(f"📉 سرعت این هفته {fa_num(abs(change))}٪ کمتر از هفته قبل.")
            lines.append("")

    lines.append("_برای جزئیات بیشتر داشبورد را باز کن._")
    return "\n".join(lines)
