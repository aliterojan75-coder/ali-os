"""Tests for Notification System (§18)."""

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest

from app import db, repositories as repo
from app.crm import repository as crm_repo
from app.notifications.service import generate_notifications, get_notification_summary, create_notification


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), f"t_{uuid.uuid4().hex}.db")
    from app.config import config
    monkeypatch.setattr(config, "DATABASE_PATH", Path(path))
    db._LOCAL.conn = None
    db.init_db()
    yield
    db._LOCAL.conn = None


@pytest.fixture()
def user():
    return repo.upsert_user(555001, "ali", "Ali")


@pytest.fixture()
def project():
    return repo.create_project("testproj", "پروژه تست")


def test_overdue_task_notification(project):
    now = time.time()
    repo.create_task(title="معوق", project_id=project["id"], priority="urgent", due_at=now - 86400 * 2)
    # Update due_at manually (create_task doesn't set due_at)
    db.execute("UPDATE tasks SET due_at=? WHERE title='معوق'", (now - 86400 * 2,))

    notifs = generate_notifications(project_id=project["id"])
    overdue = [n for n in notifs if n["type"] == "overdue_task"]
    assert len(overdue) == 1
    assert overdue[0]["severity"] == "high"


def test_due_today_notification(project):
    now = time.time()
    from datetime import datetime, timezone, timedelta
    from app.utils.jalali import TEHRAN_TZ
    now_dt = datetime.fromtimestamp(now, TEHRAN_TZ)
    today_noon = now_dt.replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
    if today_noon < now:
        today_noon += 3600  # ensure future today

    repo.create_task(title="امروز", project_id=project["id"], due_at=today_noon)
    db.execute("UPDATE tasks SET due_at=? WHERE title='امروز'", (today_noon,))

    notifs = generate_notifications(project_id=project["id"])
    due_today = [n for n in notifs if n["type"] == "task_due_today"]
    assert len(due_today) == 1


def test_approval_expiring_notification(user, project):
    # Create pending action expiring soon
    repo.create_pending_action(
        action_type="wordpress.publish",
        title="انتشار مقاله",
        risk="red",
        requested_by=user["id"],
        project_id=project["id"],
        approvals_required=2,
        ttl_seconds=3600,  # 1h
        status="pending",
    )
    notifs = generate_notifications(project_id=project["id"])
    expiring = [n for n in notifs if n["type"] in ("approval_expiring", "approval_expired")]
    assert len(expiring) >= 1


def test_crm_followup_notification(user, project):
    c = crm_repo.create_contact(name="مشتری", project_id=project["id"])
    now = time.time()
    crm_repo.add_interaction(
        contact_id=c["id"],
        project_id=project["id"],
        summary="پیگیری قرارداد",
        next_follow_up_at=now - 86400,
        created_by=user["id"],
    )

    notifs = generate_notifications(project_id=project["id"])
    crm_notifs = [n for n in notifs if "crm_followup" in n["type"]]
    assert len(crm_notifs) >= 1
    assert any(n["type"] == "crm_followup_overdue" for n in crm_notifs)


def test_notification_summary(project):
    now = time.time()
    repo.create_task(title="معوق", project_id=project["id"], priority="urgent", due_at=now - 86400)
    db.execute("UPDATE tasks SET due_at=? WHERE title='معوق'", (now - 86400,))

    summary = get_notification_summary(project_id=project["id"])
    assert summary["total"] >= 1
    assert summary["high_priority"] >= 1
    assert summary["has_critical"] is True


def test_persisted_notifications(user):
    n = create_notification(
        user_id=user["id"],
        type="custom",
        title="تست اعلان",
        body="این یک اعلان تستی است",
    )
    assert n["notification_uid"].startswith("notif_")

    from app.notifications.service import list_persisted_notifications, mark_as_read

    listed = list_persisted_notifications(user_id=user["id"])
    assert len(listed) == 1

    ok = mark_as_read(n["notification_uid"])
    assert ok is True

    unread = list_persisted_notifications(user_id=user["id"], unread_only=True)
    assert len(unread) == 0
