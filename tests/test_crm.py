"""Tests for CRM base (§14)."""

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), f"test_{uuid.uuid4().hex}.db")

import pytest

from app import db, repositories as repo
from app.crm import repository as crm_repo
from app.approvals import gateway, registry
import app.approvals.actions  # noqa: F401 (registers executors)


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
    return repo.create_project("testproj", "پروژه تست", domain="test.ir")


def test_create_contact(user, project):
    c = crm_repo.create_contact(
        name="علی رضایی",
        project_id=project["id"],
        company="Net Nova",
        phone="09123456789",
        status="lead",
        created_by=user["id"],
    )
    assert c["name"] == "علی رضایی"
    assert c["contact_uid"].startswith("crmc_")
    assert c["status"] == "lead"

    listed = crm_repo.list_contacts(project_id=project["id"])
    assert len(listed) == 1


def test_contact_search(user, project):
    crm_repo.create_contact(name="حسین", company="گیاهکده", project_id=project["id"])
    crm_repo.create_contact(name="رضا", company="Net Nova", project_id=project["id"])

    res = crm_repo.list_contacts(search="گیاهکده")
    assert len(res) == 1
    assert res[0]["name"] == "حسین"


def test_update_contact(user, project):
    c = crm_repo.create_contact(name="تست", project_id=project["id"])
    updated = crm_repo.update_contact(c["contact_uid"], status="customer", company="NewCo")
    assert updated["status"] == "customer"
    assert updated["company"] == "NewCo"


def test_interaction_and_followup(user, project):
    c = crm_repo.create_contact(name="مشتری", project_id=project["id"])
    import time
    now = time.time()
    overdue_ts = now - 86400  # yesterday
    future_ts = now + 86400 * 2

    i1 = crm_repo.add_interaction(
        contact_id=c["id"],
        project_id=project["id"],
        summary="تماس اول",
        type="call",
        next_follow_up_at=overdue_ts,
        created_by=user["id"],
    )
    assert i1["interaction_uid"].startswith("crmi_")

    i2 = crm_repo.add_interaction(
        contact_id=c["id"],
        project_id=project["id"],
        summary="جلسه بعدی",
        type="meeting",
        next_follow_up_at=future_ts,
    )

    overdue = crm_repo.upcoming_followups(overdue_only=True)
    assert len(overdue) == 1
    assert overdue[0]["summary"] == "تماس اول"

    upcoming = crm_repo.upcoming_followups(within_days=3)
    assert len(upcoming) == 2


def test_deals(user, project):
    c = crm_repo.create_contact(name="مشتری", project_id=project["id"])
    d = crm_repo.create_deal(
        title="پروژه سایت",
        contact_id=c["id"],
        project_id=project["id"],
        amount=50_000_000,
        stage="proposal",
        probability=70,
    )
    assert d["deal_uid"].startswith("crmd_")
    assert d["stage"] == "proposal"

    listed = crm_repo.list_deals(project_id=project["id"])
    assert len(listed) == 1

    updated = crm_repo.update_deal(d["deal_uid"], stage="won")
    assert updated["stage"] == "won"

    stats = crm_repo.crm_stats(project_id=project["id"])
    assert stats["contacts_total"] == 1
    assert stats["deals_total"] == 1
    assert stats["deals_by_stage"]["won"] == 1


def test_approval_gateway_crm(user, project):
    # Green actions should execute immediately
    res = gateway.request_action(
        action_type="crm.create_contact",
        title="مخاطب جدید",
        payload={"name": "تست", "project_id": project["id"]},
        requested_by=user["id"],
        project_id=project["id"],
        chat_id=999,
    )
    assert res.executed is True
    contacts = crm_repo.list_contacts(project_id=project["id"])
    assert len(contacts) == 1

    # Yellow action should require approval
    c = contacts[0]
    res2 = gateway.request_action(
        action_type="crm.update_contact",
        title="ویرایش مخاطب",
        payload={"contact_uid": c["contact_uid"], "status": "customer"},
        requested_by=user["id"],
        project_id=project["id"],
        chat_id=999,
    )
    assert res2.executed is False
    # Before approval, status unchanged
    fresh = crm_repo.get_contact(c["contact_uid"])
    assert fresh["status"] == "lead"

    # Approve
    gateway.approve(res2.action_uid, 555001)
    fresh2 = crm_repo.get_contact(c["contact_uid"])
    assert fresh2["status"] == "customer"

    # Red action: delete contact requires 2 approvals
    res3 = gateway.request_action(
        action_type="crm.delete_contact",
        title="حذف مخاطب",
        payload={"contact_uid": c["contact_uid"]},
        requested_by=user["id"],
        project_id=project["id"],
        chat_id=999,
    )
    assert res3.executed is False
    assert res3.risk == "red"
    # First approval -> confirming
    a1, r1, t1 = gateway.approve(res3.action_uid, 555001)
    assert r1 is None
    assert a1["status"] == "confirming"
    # Second approval -> executed
    a2, r2, t2 = gateway.approve(res3.action_uid, 555001)
    assert r2.executed is True
    assert crm_repo.get_contact(c["contact_uid"]) is None
