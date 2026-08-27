"""Notification System (§18) — overdue tasks, expiring approvals, CRM followups.

This module computes notifications on the fly from current DB state,
and optionally persists them in the notifications table for read/unread tracking.
"""

from __future__ import annotations

import time
from typing import Any

from app import db, repositories as repo
from app.crm import repository as crm_repo
from app.utils.jalali import format_timestamp_fa, fa_num


def _now() -> float:
    return time.time()


def generate_notifications(
    *,
    user_id: int | None = None,
    project_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Generate current notifications from DB state — no persistence."""
    now = _now()
    notifications: list[dict] = []

    # 1. Overdue tasks
    all_open = repo.list_tasks(project_id=project_id, limit=200)
    for t in all_open:
        due = t["due_at"]
        if due is not None and due < now:
            overdue_days = int((now - due) / 86400)
            # Any overdue urgent/high is high, otherwise medium unless very overdue
            is_hot = t["priority"] in ("urgent", "high")
            sev = "high" if (is_hot or overdue_days >= 1) else "medium"
            if overdue_days >= 3:
                sev = "high"
            notifications.append({
                "type": "overdue_task",
                "severity": sev,
                "title": f"تسک معوق: {t['title']}",
                "body": f"{t['project_name'] or 'بدون پروژه'} — {overdue_days} روز معوق — اولویت {t['priority']}",
                "related_type": "task",
                "related_id": t["task_uid"],
                "created_at": t["due_at"],
                "meta": {"overdue_days": overdue_days, "priority": t["priority"]},
            })

    # 2. Tasks due today/tomorrow
    from datetime import datetime, timezone, timedelta
    from app.utils.jalali import TEHRAN_TZ
    now_dt = datetime.fromtimestamp(now, TEHRAN_TZ)
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    tomorrow_start = today_start + 86400
    day_after = tomorrow_start + 86400

    for t in all_open:
        due = t["due_at"]
        if due is None:
            continue
        if today_start <= due < tomorrow_start:
            notifications.append({
                "type": "task_due_today",
                "severity": "medium",
                "title": f"امروز موعد: {t['title']}",
                "body": f"{t['project_name'] or ''} — امروز",
                "related_type": "task",
                "related_id": t["task_uid"],
                "created_at": due,
                "meta": {},
            })
        elif tomorrow_start <= due < day_after:
            notifications.append({
                "type": "task_due_tomorrow",
                "severity": "low",
                "title": f"فردا موعد: {t['title']}",
                "body": f"{t['project_name'] or ''} — فردا",
                "related_type": "task",
                "related_id": t["task_uid"],
                "created_at": due,
                "meta": {},
            })

    # 3. Hot tasks (urgent without due date or long-standing)
    for t in all_open:
        if t["priority"] == "urgent" and t["status"] in ("inbox", "planned", "in_progress"):
            # If not already counted as overdue
            if not any(n["related_id"] == t["task_uid"] and n["type"] == "overdue_task" for n in notifications):
                notifications.append({
                    "type": "hot_task",
                    "severity": "high",
                    "title": f"فوری: {t['title']}",
                    "body": f"{t['project_name'] or ''} — اولویت فوری",
                    "related_type": "task",
                    "related_id": t["task_uid"],
                    "created_at": t["created_at"],
                    "meta": {"priority": t["priority"]},
                })

    # 4. Approvals expiring soon
    pending = repo.list_pending_actions(limit=50)
    for a in pending:
        expires = a["expires_at"]
        if expires is None:
            continue
        remaining = expires - now
        if remaining < 0:
            notifications.append({
                "type": "approval_expired",
                "severity": "high",
                "title": f"منقضی شد: {a['title']}",
                "body": f"نوع: {a['action_type']} — ریسک {a['risk']}",
                "related_type": "approval",
                "related_id": a["action_uid"],
                "created_at": expires,
                "meta": {"risk": a["risk"]},
            })
        elif remaining < 2 * 3600:  # <2h
            mins = int(remaining / 60)
            notifications.append({
                "type": "approval_expiring",
                "severity": "high" if a["risk"] == "red" else "medium",
                "title": f"در حال انقضا: {a['title']}",
                "body": f"{mins} دقیقه تا انقضا — {a['risk']}",
                "related_type": "approval",
                "related_id": a["action_uid"],
                "created_at": a["created_at"],
                "meta": {"remaining_minutes": mins, "risk": a["risk"]},
            })

    # 5. CRM followups overdue
    try:
        overdue_followups = crm_repo.upcoming_followups(project_id=project_id, overdue_only=True, limit=20)
        for f in overdue_followups:
            overdue_days = int((now - f["next_follow_up_at"]) / 86400) if f["next_follow_up_at"] else 0
            notifications.append({
                "type": "crm_followup_overdue",
                "severity": "medium",
                "title": f"پیگیری معوق: {f['contact_name']}",
                "body": f"{f['summary']} — {overdue_days} روز معوق",
                "related_type": "crm_interaction",
                "related_id": f["interaction_uid"],
                "created_at": f["next_follow_up_at"],
                "meta": {"contact_name": f["contact_name"]},
            })

        upcoming = crm_repo.upcoming_followups(project_id=project_id, within_days=2, limit=20)
        for f in upcoming:
            # Avoid double-counting overdue
            if f["next_follow_up_at"] and f["next_follow_up_at"] <= now:
                continue
            notifications.append({
                "type": "crm_followup_upcoming",
                "severity": "low",
                "title": f"پیگیری پیش رو: {f['contact_name']}",
                "body": f["summary"],
                "related_type": "crm_interaction",
                "related_id": f["interaction_uid"],
                "created_at": f["next_follow_up_at"],
                "meta": {},
            })
    except Exception:
        pass

    # Sort by severity and recency
    severity_order = {"high": 0, "medium": 1, "low": 2}
    notifications.sort(key=lambda n: (severity_order.get(n["severity"], 1), - (n["created_at"] or 0)))

    return notifications[:limit]


def list_persisted_notifications(
    *,
    user_id: int | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    sql = "SELECT * FROM notifications WHERE 1=1"
    params: list[Any] = []
    if user_id is not None:
        sql += " AND user_id=?"
        params.append(user_id)
    if unread_only:
        sql += " AND is_read=0"
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.query_all(sql, tuple(params))
    return [dict(r) for r in rows]


def mark_as_read(notification_uid: str) -> bool:
    cur = db.execute("UPDATE notifications SET is_read=1 WHERE notification_uid=?", (notification_uid,))
    return getattr(cur, "rowcount", 1) > 0


def mark_all_read(user_id: int | None = None) -> int:
    if user_id is not None:
        cur = db.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0", (user_id,))
    else:
        cur = db.execute("UPDATE notifications SET is_read=1 WHERE is_read=0")
    return getattr(cur, "rowcount", 0)


def create_notification(
    *,
    user_id: int | None = None,
    type: str,
    title: str,
    body: str | None = None,
    related_type: str | None = None,
    related_id: str | None = None,
) -> dict:
    uid = db.new_uid("notif")
    t = db.now()
    db.execute(
        """INSERT INTO notifications
           (notification_uid, user_id, type, title, body, related_type, related_id, is_read, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (uid, user_id, type, title, body, related_type, related_id, t),
    )
    row = db.query_one("SELECT * FROM notifications WHERE notification_uid=?", (uid,))
    return dict(row) if row else {}


def get_notification_summary(
    *,
    user_id: int | None = None,
    project_id: int | None = None,
) -> dict:
    """Quick summary for dashboard / telegram."""
    live = generate_notifications(user_id=user_id, project_id=project_id, limit=100)
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for n in live:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        by_severity[n["severity"]] = by_severity.get(n["severity"], 0) + 1

    persisted_unread = 0
    try:
        row = db.query_one(
            "SELECT COUNT(*) AS c FROM notifications WHERE is_read=0" + (" AND user_id=?" if user_id else ""),
            (user_id,) if user_id else (),
        )
        persisted_unread = row["c"] if row else 0
    except Exception:
        pass

    return {
        "total": len(live),
        "by_type": by_type,
        "by_severity": by_severity,
        "high_priority": by_severity.get("high", 0),
        "persisted_unread": persisted_unread,
        "has_critical": by_severity.get("high", 0) > 0,
    }
