"""Automation / Cron jobs (§16) — morning report + notifications.

This module is called by:
- cron-job.org / GitHub Actions via GET /internal/cron?secret=...
- Or internally via APScheduler if configured

It sends the morning report and critical notifications to Telegram.
"""

from __future__ import annotations

import time
from typing import Any

from app import repositories as repo
from app.agents.pm_agent import generate_morning_report, format_morning_report_telegram
from app.config import config
from app.logging_config import get_logger
from app.notifications.service import generate_notifications
from app.telegram import send_message

log = get_logger("automation")


def _get_owner_chat_id() -> int | None:
    """Find the owner's chat_id from recent conversations or users."""
    try:
        # Get the most recent conversation with chat_id
        from app import db
        row = db.query_one("SELECT chat_id FROM conversations WHERE chat_id IS NOT NULL ORDER BY started_at DESC LIMIT 1")
        if row and row["chat_id"]:
            return int(row["chat_id"])
    except Exception:
        pass
    return None


def run_morning_job(*, project_id: int | None = None, chat_id: int | None = None) -> dict:
    """Generate and send morning report."""
    owner_chat = chat_id or _get_owner_chat_id()
    if not owner_chat:
        log.warning("automation.no_chat_id", extra={"extra_fields": {}})
        return {"ok": False, "error": "no chat_id found — send /start first"}

    report = generate_morning_report(project_id=project_id)
    text = format_morning_report_telegram(report)

    try:
        sent = send_message(chat_id=owner_chat, text=text)
        repo.record_event(
            "morning_report_sent", payload={"chat_id": owner_chat, "project_id": project_id, "counts": report["counts"]}
        )
        return {"ok": True, "sent_message_id": sent.get("message_id"), "report": report}
    except Exception as exc:
        log.exception("automation.morning_failed", extra={"extra_fields": {"error": str(exc)}})
        return {"ok": False, "error": str(exc)}


def run_notifications_job(*, project_id: int | None = None, chat_id: int | None = None, min_severity: str = "high") -> dict:
    """Send critical notifications."""
    owner_chat = chat_id or _get_owner_chat_id()
    if not owner_chat:
        return {"ok": False, "error": "no chat_id"}

    notifs = generate_notifications(project_id=project_id, limit=20)
    # Filter by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    min_level = severity_order.get(min_severity, 0)
    critical = [n for n in notifs if severity_order.get(n["severity"], 1) <= min_level]

    if not critical:
        return {"ok": True, "sent": 0, "message": "no critical notifications"}

    lines = [f"🔔 {len(critical)} اعلان مهم:"]
    for n in critical[:8]:
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(n["severity"], "•")
        lines.append(f"{emoji} {n['title']}")
        if n["body"]:
            lines.append(f"   {n['body']}")

    text = "\n".join(lines)
    try:
        sent = send_message(chat_id=owner_chat, text=text)
        repo.record_event("notifications_sent", payload={"chat_id": owner_chat, "count": len(critical)})
        return {"ok": True, "sent": len(critical), "message_id": sent.get("message_id")}
    except Exception as exc:
        log.exception("automation.notify_failed", extra={"extra_fields": {"error": str(exc)}})
        return {"ok": False, "error": str(exc)}


def run_daily_jobs(*, chat_id: int | None = None) -> dict:
    """Run all daily jobs — morning report + notifications."""
    results: dict[str, Any] = {"started_at": time.time()}
    results["morning"] = run_morning_job(chat_id=chat_id)
    # Small delay to avoid Telegram rate limit
    time.sleep(1)
    results["notifications"] = run_notifications_job(chat_id=chat_id, min_severity="high")
    results["finished_at"] = time.time()
    results["ok"] = results["morning"].get("ok") or results["notifications"].get("ok")
    return results
