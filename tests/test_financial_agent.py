"""Tests for Financial Agent — automated payment reminders."""

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest

from app import db, repositories as repo
from app.crm.repository import create_contact
from app.financial.repository import create_income
from app.agents.financial_agent import generate_reminder_message, send_overdue_reminders, format_overdue_summary_telegram
from app.approvals import gateway
import app.approvals.actions  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), f"t_{uuid.uuid4().hex}.db")
    from app.config import config
    monkeypatch.setattr(config, "DATABASE_PATH", Path(path))
    db._LOCAL.conn = None
    db.init_db()

    sent = []
    stubs = {
        "send_message": lambda **kw: (sent.append(kw), {"message_id": 4242})[1],
        "edit_message_text": lambda *a, **kw: {},
        "answer_callback_query": lambda *a, **kw: {},
    }
    for module in ("app.telegram.client", "app.telegram"):
        for name, fn in stubs.items():
            monkeypatch.setattr(f"{module}.{name}", fn)
    yield
    db._LOCAL.conn = None


@pytest.fixture()
def user():
    return repo.upsert_user(555001, "ali", "Ali")


@pytest.fixture()
def project():
    return repo.create_project("giahkade", "گیاهکده")


def test_generate_reminder_message(project, user):
    c = create_contact(name="رضا", company="شرکت تست", project_id=project["id"], email="reza@test.com", status="customer")
    now = time.time()
    inc = create_income(
        project_id=project["id"],
        amount=15_000_000,
        month_jalali="1404-06",
        status="pending",
        due_at=now - 2 * 86400,  # 2 days overdue
        created_by=user["id"],
    )

    reminder = generate_reminder_message(inc["income_uid"], template="overdue")
    assert "رضا" in reminder["message"]
    assert "گیاهکده" in reminder["message"]
    assert "15,000,000" in reminder["message"] or "15000000" in reminder["message"]
    assert "1404-06" in reminder["message"]
    assert "خودکار" in reminder["message"]  # must state it's automated
    assert "نت نوا" in reminder["message"] or "نت نوا" in reminder["message"] or "آژانس" in reminder["message"]
    assert reminder["days_overdue"] >= 1
    assert reminder["client"] is not None


def test_reminder_templates_contain_automation_note(project):
    inc = create_income(project_id=project["id"], amount=10_000_000, month_jalali="1404-06", status="pending", due_at=time.time() - 86400)

    for tpl in ("first", "overdue", "second_overdue"):
        reminder = generate_reminder_message(inc["income_uid"], template=tpl)
        msg = reminder["message"]
        # Must clearly state it's automated, not personal from Ali
        assert "خودکار" in msg
        assert "دستیار" in msg or "Ali OS" in msg or "نت نوا" in msg


def test_send_overdue_reminders_dry_run(project, user):
    create_contact(name="مشتری", project_id=project["id"], status="customer")
    now = time.time()
    create_income(project_id=project["id"], amount=10_000_000, month_jalali="1404-05", status="pending", due_at=now - 3 * 86400)
    create_income(project_id=project["id"], amount=12_000_000, month_jalali="1404-06", status="pending", due_at=now - 1 * 86400)

    results = send_overdue_reminders(project_id=project["id"], dry_run=True, max_send=5)
    assert len(results) == 2
    assert all(r["dry_run"] is True for r in results)
    assert all("message" in r for r in results)
    assert all("خودکار" in r["message"] for r in results)

    summary = format_overdue_summary_telegram(results)
    assert "پرداخت‌های معوق" in summary or "معوق" in summary


def test_send_overdue_reminders_with_approval(project, user):
    c = create_contact(name="مشتری", project_id=project["id"], status="customer", telegram_chat_id=123456789)
    now = time.time()
    create_income(project_id=project["id"], amount=10_000_000, month_jalali="1404-05", status="pending", due_at=now - 2 * 86400)

    # Dry run False should request approval
    results = send_overdue_reminders(project_id=project["id"], dry_run=False, max_send=5)
    assert len(results) == 1
    assert results[0]["dry_run"] is False
    assert results[0]["send_result"]["method"] == "telegram_client"
    # Should have created a pending action
    assert results[0]["send_result"]["action_uid"] is not None

    # Approve it
    action_uid = results[0]["send_result"]["action_uid"]
    action, result, toast = gateway.approve(action_uid, 555001)
    assert result.executed is True
    assert "ارسال شد" in result.result or "یادآوری" in result.result
