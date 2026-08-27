"""Tests for Financial monthly income tracking (redefined §15)."""

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
from app.financial.repository import (
    create_income,
    get_income,
    list_incomes,
    mark_paid,
    update_income,
    delete_income,
    monthly_summary,
    project_contracts_summary,
    mark_overdue_if_needed,
)
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


def test_create_income(project, user):
    inc = create_income(
        project_id=project["id"],
        amount=15_000_000,
        month_jalali="1404-06",
        currency="IRT",
        status="pending",
        created_by=user["id"],
    )
    assert inc["income_uid"].startswith("inc_")
    assert inc["month_jalali"] == "1404-06"
    assert float(inc["amount"]) == 15_000_000

    listed = list_incomes(project_id=project["id"])
    assert len(listed) == 1


def test_monthly_summary(project):
    create_income(project_id=project["id"], amount=10_000_000, month_jalali="1404-05", status="paid")
    create_income(project_id=project["id"], amount=15_000_000, month_jalali="1404-06", status="pending")
    # Different project same month
    other_proj = repo.create_project("other", "پروژه دیگر")
    create_income(project_id=other_proj["id"], amount=12_000_000, month_jalali="1404-06", status="paid")

    summary = monthly_summary(project_id=project["id"])
    assert summary["total_paid"] == 10_000_000  # only 10M paid for this project
    assert summary["total_expected"] == 25_000_000  # 10M + 15M
    assert len(summary["months"]) == 2
    assert summary["current_month"]  # should be set

    # Global summary should include both projects
    global_summary = monthly_summary()
    assert global_summary["total_paid"] == 22_000_000  # 10M + 12M
    assert global_summary["total_expected"] == 37_000_000


def test_mark_paid(project):
    inc = create_income(project_id=project["id"], amount=20_000_000, month_jalali="1404-06", status="pending")
    assert inc["status"] == "pending"

    paid = mark_paid(inc["income_uid"], payment_method="کارت به کارت", transaction_ref="12345")
    assert paid["status"] == "paid"
    assert paid["paid_at"] is not None
    assert paid["payment_method"] == "کارت به کارت"


def test_overdue_detection(project):
    now = time.time()
    # Create overdue income (due yesterday)
    inc = create_income(
        project_id=project["id"],
        amount=10_000_000,
        month_jalali="1404-05",
        status="pending",
        due_at=now - 86400,
    )
    assert inc["status"] == "pending"

    count = mark_overdue_if_needed()
    assert count >= 1

    fresh = get_income(inc["income_uid"])
    assert fresh["status"] == "overdue"


def test_project_contracts_summary():
    p1 = repo.create_project("proj1", "پروژه ۱")
    p2 = repo.create_project("proj2", "پروژه ۲")

    create_income(project_id=p1["id"], amount=10_000_000, month_jalali="1404-04", status="paid")
    create_income(project_id=p1["id"], amount=12_000_000, month_jalali="1404-05", status="paid")
    create_income(project_id=p1["id"], amount=11_000_000, month_jalali="1404-06", status="pending")

    create_income(project_id=p2["id"], amount=20_000_000, month_jalali="1404-06", status="paid")

    contracts = project_contracts_summary()
    # Should have at least 2
    assert len(contracts) >= 2

    p1_contract = next((c for c in contracts if c["slug"] == "proj1"), None)
    assert p1_contract is not None
    # Average of 10M and 12M = 11M
    assert p1_contract["avg_contract"] == 11_000_000


def test_income_approval_flow(project, user):
    # income.create is green — should execute immediately
    res = gateway.request_action(
        action_type="income.create",
        title="درآمد تست",
        payload={"project_id": project["id"], "amount": 15_000_000, "month_jalali": "1404-06"},
        requested_by=user["id"],
        project_id=project["id"],
        chat_id=999,
    )
    assert res.executed is True

    incomes = list_incomes(project_id=project["id"])
    assert len(incomes) == 1

    # income.delete is yellow — requires approval
    inc = incomes[0]
    res2 = gateway.request_action(
        action_type="income.delete",
        title="حذف درآمد",
        payload={"income_uid": inc["income_uid"]},
        requested_by=user["id"],
        project_id=project["id"],
        chat_id=999,
    )
    assert res2.executed is False

    # Approve
    gateway.approve(res2.action_uid, 555001)
    assert get_income(inc["income_uid"]) is None


def test_invalid_month_format(project):
    with pytest.raises(ValueError):
        create_income(project_id=project["id"], amount=10_000_000, month_jalali="invalid")
