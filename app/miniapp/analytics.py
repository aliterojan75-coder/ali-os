"""Aggregations that power the dashboard charts.

Timestamps are stored as REAL unix seconds, so all bucketing is done in Python
rather than with SQLite date functions — that keeps the queries identical on
local SQLite and on Turso/libSQL over HTTP.
"""
from __future__ import annotations

import time
import sqlite3
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
    """Per-project rollup used by the projects screen.

    The previous version did two extra queries per project (KPIs and
    integrations). Against remote Turso that was seconds of latency. This keeps
    it to three bounded round-trips: task rollup, KPI rollup, integration rollup.
    """
    rows = db.query_all(
        """SELECT p.id, p.name, p.slug, p.status, p.domain,
                  SUM(CASE WHEN t.status NOT IN ('done','cancelled') THEN 1 ELSE 0 END) AS open_tasks,
                  SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) AS done_tasks,
                  SUM(CASE WHEN t.priority IN ('urgent','high')
                            AND t.status NOT IN ('done','cancelled') THEN 1 ELSE 0 END) AS hot_tasks
           FROM projects p LEFT JOIN tasks t ON t.project_id = p.id
           GROUP BY p.id ORDER BY p.name"""
    )
    kpi_rows = db.query_all(
        """SELECT project_id, target_value, current_value, direction
           FROM project_kpis"""
    )
    kpis_by_project: dict[int, list[sqlite3.Row]] = {}
    for k in kpi_rows:
        kpis_by_project.setdefault(k["project_id"], []).append(k)

    conn_rows = db.query_all(
        """SELECT project_id, COUNT(*) AS c FROM integrations
           WHERE project_id IS NOT NULL AND status='connected'
           GROUP BY project_id"""
    )
    connections = {r["project_id"]: r["c"] for r in conn_rows}

    out = []
    for r in rows:
        open_t = r["open_tasks"] or 0
        done_t = r["done_tasks"] or 0
        total = open_t + done_t
        kpis = kpis_by_project.get(r["id"], [])
        kpi_scores = []
        for k in kpis:
            target, current = k["target_value"], k["current_value"]
            if not target or current is None:
                continue
            pct = (current / target) if k["direction"] == "up" else (
                target / current if current else 0)
            kpi_scores.append(max(0.0, min(pct, 1.5)))
        kpi_avg = round(sum(kpi_scores) / len(kpi_scores) * 100) if kpi_scores else None
        out.append({
            "id": r["id"], "name": r["name"], "slug": r["slug"],
            "status": r["status"], "domain": r["domain"],
            "open_tasks": open_t, "done_tasks": done_t,
            "hot_tasks": r["hot_tasks"] or 0,
            "completion": round(done_t / total * 100) if total else None,
            "kpi_score": kpi_avg,
            "kpi_count": len(kpis),
            "connections": connections.get(r["id"], 0),
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
    """This week vs. last week — one SQL round-trip even on remote Turso."""
    now = time.time()
    week, two_weeks = now - 7 * 86400, now - 14 * 86400

    row = db.query_one(
        """SELECT
             SUM(CASE WHEN status='done' AND updated_at >= ? THEN 1 ELSE 0 END) AS this_done,
             SUM(CASE WHEN status='done' AND updated_at >= ? AND updated_at < ? THEN 1 ELSE 0 END) AS last_done,
             SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS this_created
           FROM tasks""",
        (week, two_weeks, week, week),
    ) or {}
    this_done = int(row["this_done"] or 0)
    last_done = int(row["last_done"] or 0)
    this_created = int(row["this_created"] or 0)

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
    """Small dashboard business card without invoking the full agent.

    Full `/api/business/analysis` remains available (and cached); the overview
    card only needs counts and top recommendations, so one SELECT with
    subqueries avoids a cascade of Turso round-trips on every dashboard load.
    """
    try:
        now = time.time()
        stale_cutoff = now - 14 * 86400
        row = db.query_one(
            """SELECT
              (SELECT COUNT(*) FROM tasks WHERE status NOT IN ('done','cancelled')) AS open_tasks,
              (SELECT COUNT(*) FROM tasks WHERE due_at IS NOT NULL AND due_at < ? AND status NOT IN ('done','cancelled')) AS overdue_tasks,
              (SELECT COUNT(*) FROM tasks WHERE priority IN ('urgent','high') AND status NOT IN ('done','cancelled')) AS hot_tasks,
              (SELECT COUNT(*) FROM crm_deals) AS deals_total,
              (SELECT COUNT(*) FROM crm_deals WHERE stage NOT IN ('won','lost') AND updated_at < ?) AS stale_deals,
              (SELECT COUNT(*) FROM crm_interactions WHERE next_follow_up_at IS NOT NULL AND next_follow_up_at <= ?) AS overdue_followups,
              (SELECT COUNT(*) FROM content_drafts WHERE status IN ('draft','pending_approval')) AS unpublished_content,
              (SELECT COUNT(*) FROM pending_actions WHERE status IN ('pending','confirming')) AS pending_approvals
            """,
            (now, stale_cutoff, now),
        ) or {}
        counts = {k: int(row[k] or 0) for k in (
            "open_tasks", "overdue_tasks", "hot_tasks", "deals_total",
            "stale_deals", "overdue_followups", "unpublished_content",
            "pending_approvals",
        )}
        deductions = (
            counts["overdue_tasks"] * 4 + counts["hot_tasks"] * 2 +
            counts["stale_deals"] * 5 + counts["overdue_followups"] * 5 +
            max(0, counts["pending_approvals"] - 5) * 3
        )
        score = max(0, min(100, 100 - deductions))
        recs: list[str] = []
        if counts["overdue_tasks"]:
            recs.append("اول تسک‌های معوق را تعیین تکلیف کن")
        if counts["overdue_followups"]:
            recs.append("پیگیری‌های معوق CRM را تماس بگیر")
        if counts["stale_deals"]:
            recs.append("معاملات راکد را پیگیری یا مرحله را به‌روزرسانی کن")
        if counts["pending_approvals"] > 5:
            recs.append("صف تأیید را خلوت کن")
        insights_count = sum(1 for k in ("overdue_tasks", "hot_tasks", "stale_deals", "overdue_followups", "unpublished_content") if counts[k])
        return {
            "health_score": score,
            "health_label": "عالی" if score >= 85 else "خوب" if score >= 70 else "متوسط" if score >= 50 else "نیاز به توجه",
            "insights_count": insights_count,
            "recommendations": recs[:3],
            "counts": counts,
        }
    except Exception:
        return {"health_score": 0, "health_label": "—", "insights_count": 0, "recommendations": [], "counts": {}}


def sales_overview() -> dict:
    """Small sales card in one grouped query."""
    try:
        now = time.time()
        stale_cutoff = now - 7 * 86400
        close_until = now + 7 * 86400
        rows = db.query_all(
            """SELECT stage, COUNT(*) AS c,
                      COALESCE(SUM(CASE WHEN stage NOT IN ('won','lost') THEN amount ELSE 0 END),0) AS open_amount,
                      COALESCE(SUM(CASE WHEN stage NOT IN ('won','lost') THEN amount * COALESCE(probability,50) / 100.0 ELSE 0 END),0) AS weighted,
                      SUM(CASE WHEN stage NOT IN ('won','lost') AND updated_at < ? THEN 1 ELSE 0 END) AS stale,
                      SUM(CASE WHEN stage NOT IN ('won','lost') AND expected_close_at IS NOT NULL AND expected_close_at >= ? AND expected_close_at <= ? THEN 1 ELSE 0 END) AS closing
               FROM crm_deals GROUP BY stage""",
            (stale_cutoff, now, close_until),
        )
        by_stage: dict[str, int] = {}
        total = 0
        pipeline = 0.0
        weighted = 0.0
        stale = 0
        closing = 0
        for r in rows:
            by_stage[r["stage"]] = r["c"]
            total += r["c"]
            pipeline += float(r["open_amount"] or 0)
            weighted += float(r["weighted"] or 0)
            stale += int(r["stale"] or 0)
            closing += int(r["closing"] or 0)
        return {
            "total_deals": total,
            "pipeline_value": pipeline,
            "weighted_value": weighted,
            "by_stage": by_stage,
            "stale_count": stale,
            "closing_soon_count": closing,
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
    """Everything the dashboard needs, with the hot counts collapsed to one SELECT."""
    now = time.time()
    try:
        row = db.query_one(
            """SELECT
              (SELECT COUNT(*) FROM tasks WHERE status NOT IN ('done','cancelled')) AS open_tasks,
              (SELECT COUNT(*) FROM tasks WHERE status='done') AS done_tasks,
              (SELECT COUNT(*) FROM tasks WHERE due_at IS NOT NULL AND due_at < ? AND status NOT IN ('done','cancelled')) AS overdue_tasks,
              (SELECT COUNT(*) FROM projects WHERE status='active') AS active_projects,
              (SELECT COUNT(*) FROM decisions) AS decisions,
              (SELECT COUNT(*) FROM memories) AS memories,
              (SELECT COUNT(*) FROM events) AS events,
              (SELECT COUNT(*) FROM integrations WHERE status='connected') AS connections,
              (SELECT COUNT(*) FROM crm_contacts WHERE status != 'archived') AS crm_contacts,
              (SELECT COUNT(*) FROM crm_deals WHERE stage NOT IN ('won','lost')) AS crm_deals,
              (SELECT COUNT(*) FROM notifications WHERE is_read=0) AS notifications
            """,
            (now,),
        )
        keys = ("open_tasks", "done_tasks", "overdue_tasks", "active_projects",
                "decisions", "memories", "events", "connections",
                "crm_contacts", "crm_deals", "notifications")
        counts = {k: int(row[k] or 0) for k in keys} if row else {}
    except Exception:
        counts = {k: 0 for k in ("open_tasks", "done_tasks", "overdue_tasks", "active_projects",
                                 "decisions", "memories", "events", "connections",
                                 "crm_contacts", "crm_deals", "notifications")}

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
