"""Aggregations that power the dashboard charts.

Timestamps are stored as REAL unix seconds, so all bucketing is done in Python
rather than with SQLite date functions — that keeps the queries identical on
local SQLite and on Turso/libSQL over HTTP.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app import db

# Tehran is UTC+3:30 and has no DST — the user's day boundaries.
TEHRAN = timezone(timedelta(hours=3, minutes=30))

FA_WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
FA_WEEKDAYS_SHORT = ["د", "س", "چ", "پ", "ج", "ش", "ی"]


def _local_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, TEHRAN).strftime("%Y-%m-%d")


def _day_label(day: str) -> str:
    """Short Persian-digit label like ۱۲/۰۵ for chart axes."""
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{d.month}/{d.day}"


def _day_range(days: int) -> list[str]:
    today = datetime.now(TEHRAN).date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days - 1, -1, -1)]


def task_trend(days: int = 14) -> dict:
    """Tasks created vs. completed per day — the headline activity chart."""
    buckets = _day_range(days)
    created = {d: 0 for d in buckets}
    done = {d: 0 for d in buckets}
    cutoff = time.time() - days * 86400 - 86400

    for row in db.query_all(
        "SELECT created_at, updated_at, status FROM tasks WHERE created_at >= ? OR updated_at >= ?",
        (cutoff, cutoff),
    ):
        day = _local_day(row["created_at"])
        if day in created:
            created[day] += 1
        if row["status"] == "done":
            day = _local_day(row["updated_at"])
            if day in done:
                done[day] += 1

    return {
        "labels": [_day_label(d) for d in buckets],
        "days": buckets,
        "created": [created[d] for d in buckets],
        "done": [done[d] for d in buckets],
    }


def activity_heatmap(weeks: int = 8) -> dict:
    """Events per day, as a GitHub-style contribution grid."""
    days = weeks * 7
    buckets = _day_range(days)
    counts = {d: 0 for d in buckets}
    cutoff = time.time() - days * 86400 - 86400
    for row in db.query_all(
        "SELECT created_at FROM events WHERE created_at >= ?", (cutoff,)
    ):
        day = _local_day(row["created_at"])
        if day in counts:
            counts[day] += 1
    values = [counts[d] for d in buckets]
    return {
        "days": buckets,
        "values": values,
        "max": max(values) if values else 0,
        "total": sum(values),
    }


def status_breakdown() -> list[dict]:
    rows = db.query_all(
        "SELECT status, COUNT(*) AS c FROM tasks GROUP BY status ORDER BY c DESC"
    )
    labels = {
        "inbox": "ورودی", "planned": "برنامه‌ریزی‌شده", "in_progress": "در حال انجام",
        "blocked": "متوقف", "waiting_approval": "منتظر تأیید",
        "done": "انجام‌شده", "cancelled": "لغوشده",
    }
    return [{"key": r["status"], "label": labels.get(r["status"], r["status"]),
             "value": r["c"]} for r in rows]


def priority_breakdown() -> list[dict]:
    rows = db.query_all(
        """SELECT priority, COUNT(*) AS c FROM tasks
           WHERE status NOT IN ('done','cancelled') GROUP BY priority"""
    )
    labels = {"urgent": "فوری", "high": "بالا", "normal": "معمولی", "low": "کم"}
    order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    out = [{"key": r["priority"], "label": labels.get(r["priority"], r["priority"]),
            "value": r["c"]} for r in rows]
    out.sort(key=lambda x: order.get(x["key"], 9))
    return out


def approvals_summary() -> dict:
    rows = db.query_all(
        "SELECT status, risk, COUNT(*) AS c FROM pending_actions GROUP BY status, risk"
    )
    by_status: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["c"]
        by_risk[r["risk"]] = by_risk.get(r["risk"], 0) + r["c"]
    executed = by_status.get("executed", 0)
    rejected = by_status.get("rejected", 0)
    decided = executed + rejected
    return {
        "pending": by_status.get("pending", 0) + by_status.get("confirming", 0),
        "executed": executed,
        "rejected": rejected,
        "failed": by_status.get("failed", 0),
        "expired": by_status.get("expired", 0),
        "by_risk": by_risk,
        "approval_rate": round(executed / decided * 100) if decided else None,
    }


def project_health() -> list[dict]:
    """Per-project rollup used by the projects screen and the radar-ish bars."""
    rows = db.query_all(
        """SELECT p.id, p.name, p.slug, p.status, p.domain,
                  SUM(CASE WHEN t.status NOT IN ('done','cancelled') THEN 1 ELSE 0 END) AS open_tasks,
                  SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) AS done_tasks,
                  SUM(CASE WHEN t.priority IN ('urgent','high')
                            AND t.status NOT IN ('done','cancelled') THEN 1 ELSE 0 END) AS hot_tasks
           FROM projects p LEFT JOIN tasks t ON t.project_id = p.id
           GROUP BY p.id ORDER BY p.name"""
    )
    out = []
    for r in rows:
        open_t = r["open_tasks"] or 0
        done_t = r["done_tasks"] or 0
        total = open_t + done_t
        kpis = db.query_all(
            """SELECT target_value, current_value, direction FROM project_kpis
               WHERE project_id=?""", (r["id"],)
        )
        kpi_scores = []
        for k in kpis:
            target, current = k["target_value"], k["current_value"]
            if not target or current is None:
                continue
            pct = (current / target) if k["direction"] == "up" else (
                target / current if current else 0)
            kpi_scores.append(max(0.0, min(pct, 1.5)))
        kpi_avg = round(sum(kpi_scores) / len(kpi_scores) * 100) if kpi_scores else None
        integrations = db.query_one(
            "SELECT COUNT(*) AS c FROM integrations WHERE project_id=? AND status='connected'",
            (r["id"],),
        )["c"]
        out.append({
            "id": r["id"], "name": r["name"], "slug": r["slug"],
            "status": r["status"], "domain": r["domain"],
            "open_tasks": open_t, "done_tasks": done_t,
            "hot_tasks": r["hot_tasks"] or 0,
            "completion": round(done_t / total * 100) if total else None,
            "kpi_score": kpi_avg,
            "kpi_count": len(kpis),
            "connections": integrations,
        })
    return out


def kpi_overview(limit: int = 8) -> list[dict]:
    rows = db.query_all(
        """SELECT k.*, p.name AS project_name, p.slug AS project_slug
           FROM project_kpis k JOIN projects p ON p.id=k.project_id
           ORDER BY k.updated_at DESC LIMIT ?""", (limit,)
    )
    out = []
    for r in rows:
        target, current = r["target_value"], r["current_value"]
        pct = None
        if target and current is not None:
            pct = (current / target) if r["direction"] == "up" else (
                target / current if current else 0)
            pct = round(max(0.0, min(pct, 2.0)) * 100)
        out.append({
            "name": r["name"], "project": r["project_name"],
            "target": target, "current": current, "unit": r["unit"],
            "direction": r["direction"], "percent": pct,
        })
    return out


def velocity() -> dict:
    """This week vs. last week — the 'are we speeding up?' number."""
    now = time.time()
    week, two_weeks = now - 7 * 86400, now - 14 * 86400

    def _count(sql: str, params: tuple) -> int:
        return db.query_one(sql, params)["c"]

    this_done = _count(
        "SELECT COUNT(*) AS c FROM tasks WHERE status='done' AND updated_at >= ?", (week,))
    last_done = _count(
        """SELECT COUNT(*) AS c FROM tasks WHERE status='done'
           AND updated_at >= ? AND updated_at < ?""", (two_weeks, week))
    this_created = _count("SELECT COUNT(*) AS c FROM tasks WHERE created_at >= ?", (week,))

    change = None
    if last_done:
        change = round((this_done - last_done) / last_done * 100)
    elif this_done:
        change = 100
    return {
        "done_this_week": this_done,
        "done_last_week": last_done,
        "created_this_week": this_created,
        "change_percent": change,
    }


def crm_overview() -> dict:
    try:
        from app.crm.repository import crm_stats
        return crm_stats()
    except Exception:
        return {
            "contacts_total": 0,
            "contacts_by_status": {},
            "deals_total": 0,
            "deals_by_stage": {},
            "open_deals_amount": 0,
            "won_amount": 0,
            "overdue_followups": 0,
        }


def notifications_summary() -> dict:
    try:
        from app.notifications.service import get_notification_summary
        return get_notification_summary()
    except Exception:
        return {"total": 0, "by_type": {}, "by_severity": {}, "high_priority": 0, "persisted_unread": 0, "has_critical": False}


def content_overview() -> dict:
    try:
        from app.content.repository import content_stats
        return content_stats()
    except Exception:
        return {"total": 0, "by_status": {}, "avg_word_count": 0}


def business_overview() -> dict:
    try:
        from app.agents.business_analyst import analyze_business
        a = analyze_business()
        return {
            "health_score": a["health_score"],
            "health_label": a["health_label"],
            "insights_count": len(a["insights"]),
            "recommendations": a["recommendations"][:3],
            "counts": a["counts"],
        }
    except Exception:
        return {"health_score": 0, "health_label": "—", "insights_count": 0, "recommendations": [], "counts": {}}


def sales_overview() -> dict:
    try:
        from app.agents.sales_agent import analyze_sales_pipeline
        p = analyze_sales_pipeline()
        return {
            "total_deals": p["total_deals"],
            "pipeline_value": p["pipeline_value"],
            "weighted_value": p["weighted_value"],
            "by_stage": p["by_stage"],
            "stale_count": len(p["stale_deals"]),
            "closing_soon_count": len(p["closing_soon"]),
        }
    except Exception:
        return {"total_deals": 0, "pipeline_value": 0, "weighted_value": 0, "by_stage": {}, "stale_count": 0, "closing_soon_count": 0}


def financial_overview() -> dict:
    try:
        from app.financial.repository import monthly_summary, project_contracts_summary
        s = monthly_summary()
        contracts = project_contracts_summary()
        return {
            "current_month": s["current_month"],
            "total_paid": s["total_paid"],
            "total_expected": s["total_expected"],
            "collection_rate": s["collection_rate"],
            "overdue_count": len(s["overdue"]),
            "pending_count": len(s["pending"]),
            "months": s["months"][:6],
            "contracts": contracts[:8],
        }
    except Exception:
        return {"current_month": "", "total_paid": 0, "total_expected": 0, "collection_rate": 0, "overdue_count": 0, "pending_count": 0, "months": [], "contracts": []}


def gsc_trend_overview() -> dict:
    try:
        from app.integrations.gsc_storage import get_gsc_daily_trend, get_ga4_daily_trend
        # Try to get stored trends (no API call)
        gsc = get_gsc_daily_trend(days=28)
        ga4 = get_ga4_daily_trend(days=28)
        try:
            from app.integrations.gsc_storage import get_declining_pages
            declining = get_declining_pages()
        except Exception:
            declining = []
        return {"gsc": gsc, "ga4": ga4, "declining_pages": declining}
    except Exception:
        return {"gsc": {"dates": [], "clicks": [], "impressions": []}, "ga4": {"dates": [], "sessions": []}, "declining_pages": []}


def overview() -> dict:
    """Everything the dashboard needs, in one round-trip."""
    counts = {}
    for key, sql in {
        "open_tasks": "SELECT COUNT(*) AS c FROM tasks WHERE status NOT IN ('done','cancelled')",
        "done_tasks": "SELECT COUNT(*) AS c FROM tasks WHERE status='done'",
        "active_projects": "SELECT COUNT(*) AS c FROM projects WHERE status='active'",
        "decisions": "SELECT COUNT(*) AS c FROM decisions",
        "memories": "SELECT COUNT(*) AS c FROM memories",
        "events": "SELECT COUNT(*) AS c FROM events",
        "connections": "SELECT COUNT(*) AS c FROM integrations WHERE status='connected'",
        "crm_contacts": "SELECT COUNT(*) AS c FROM crm_contacts WHERE status != 'archived'",
        "crm_deals": "SELECT COUNT(*) AS c FROM crm_deals WHERE stage NOT IN ('won','lost')",
        "notifications": "SELECT COUNT(*) AS c FROM notifications WHERE is_read=0",
    }.items():
        try:
            counts[key] = db.query_one(sql)["c"]
        except Exception:
            counts[key] = 0

    # Overdue tasks quick count
    try:
        now = time.time()
        overdue = db.query_one("SELECT COUNT(*) AS c FROM tasks WHERE due_at IS NOT NULL AND due_at < ? AND status NOT IN ('done','cancelled')", (now,))["c"]
        counts["overdue_tasks"] = overdue
    except Exception:
        counts["overdue_tasks"] = 0

    return {
        "counts": counts,
        "velocity": velocity(),
        "trend": task_trend(14),
        "heatmap": activity_heatmap(8),
        "status_breakdown": status_breakdown(),
        "priority_breakdown": priority_breakdown(),
        "approvals": approvals_summary(),
        "projects": project_health(),
        "kpis": kpi_overview(),
        "crm": crm_overview(),
        "notifications": notifications_summary(),
        "content": content_overview(),
        "business": business_overview(),
        "sales": sales_overview(),
        "financial": financial_overview(),
        "gsc_trend": gsc_trend_overview(),
    }
