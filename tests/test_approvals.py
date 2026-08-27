"""Tests for the Phase 2 Approval System (§19) and project dossier (§2).

Run with:  python -m pytest tests -q
No network, no Telegram: the telegram client is monkeypatched.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)
os.environ["DATABASE_PATH"] = os.path.join(
    tempfile.mkdtemp(), f"test_{uuid.uuid4().hex}.db"
)

import pytest  # noqa: E402

from app import db, repositories as repo  # noqa: E402
from app.approvals import gateway, registry, risk  # noqa: E402
import app.approvals.actions  # noqa: F401,E402  (registers executors)


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), f"t_{uuid.uuid4().hex}.db")
    from app.config import config
    from pathlib import Path
    monkeypatch.setattr(config, "DATABASE_PATH", Path(path))
    db._LOCAL.conn = None
    db.init_db()

    # Stub out all Telegram network calls. The gateway imports these names
    # from the `app.telegram` package, so both modules must be patched.
    sent: list = []
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


# ── Risk classification ─────────────────────────────────────────────────────

def test_risk_levels_from_policy_table():
    assert risk.classify("task.create") == risk.GREEN
    assert risk.classify("wordpress.create_draft") == risk.YELLOW
    assert risk.classify("wordpress.publish") == risk.RED


def test_unknown_action_never_auto_executes():
    assert risk.classify("something.totally.new") != risk.GREEN
    assert risk.classify("customer.delete_everything") == risk.RED


def test_approvals_required_per_level():
    assert risk.approvals_required(risk.GREEN) == 0
    assert risk.approvals_required(risk.YELLOW) == 1
    assert risk.approvals_required(risk.RED) == 2


# ── Green: executes immediately ─────────────────────────────────────────────

def test_green_action_executes_and_is_audited(user, project):
    res = gateway.request_action(
        action_type="task.create",
        title="ثبت Task تست",
        payload={"title": "مقاله گلاب", "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )
    assert res.executed is True
    assert res.status == "executed"

    row = repo.get_pending_action(res.action_uid)
    assert row["status"] == "executed"
    assert row["risk"] == "green"
    tasks = repo.list_tasks(project_id=project["id"])
    assert [t["title"] for t in tasks] == ["مقاله گلاب"]


# ── Yellow: one approval ────────────────────────────────────────────────────

def test_yellow_action_waits_for_approval(user, project):
    res = gateway.request_action(
        action_type="budget.add_line",
        title="افزودن ردیف بودجه",
        payload={"label": "تبلیغات", "amount": 5_000_000, "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )
    assert res.executed is False
    assert res.status == "pending"
    assert repo.list_budget(project["id"]) == []

    action, result, toast = gateway.approve(res.action_uid, 555001)
    assert result is not None and result.executed is True
    assert action["status"] == "executed"
    budget = repo.list_budget(project["id"])
    assert len(budget) == 1 and budget[0]["label"] == "تبلیغات"


def test_reject_leaves_no_side_effect(user, project):
    res = gateway.request_action(
        action_type="budget.add_line", title="بودجه",
        payload={"label": "x", "amount": 1, "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )
    action, toast = gateway.reject(res.action_uid, 555001)
    assert action["status"] == "rejected"
    assert repo.list_budget(project["id"]) == []


def test_cannot_decide_twice(user, project):
    res = gateway.request_action(
        action_type="budget.add_line", title="بودجه",
        payload={"label": "x", "amount": 1, "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )
    gateway.approve(res.action_uid, 555001)
    with pytest.raises(gateway.DecisionError):
        gateway.approve(res.action_uid, 555001)
    with pytest.raises(gateway.DecisionError):
        gateway.reject(res.action_uid, 555001)


def test_foreign_user_cannot_approve(user, project):
    res = gateway.request_action(
        action_type="budget.add_line", title="بودجه",
        payload={"label": "x", "amount": 1, "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )
    repo.upsert_user(777, "intruder", "Someone")
    with pytest.raises(gateway.DecisionError):
        gateway.approve(res.action_uid, 777)
    assert repo.get_pending_action(res.action_uid)["status"] == "pending"


# ── Red: two-step approval ──────────────────────────────────────────────────

def test_red_action_requires_two_approvals(user, project, monkeypatch):
    calls: list = []
    registry.register("wordpress.publish",
                      lambda payload, ctx: calls.append(payload) or "published")

    res = gateway.request_action(
        action_type="wordpress.publish",
        title="انتشار مقاله گلاب",
        payload={"post_id": 12},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )
    assert res.risk == "red"
    assert repo.get_pending_action(res.action_uid)["approvals_required"] == 2

    action, result, toast = gateway.approve(res.action_uid, 555001)
    assert result is None                      # not executed yet
    assert action["status"] == "confirming"
    assert calls == []

    action, result, toast = gateway.approve(res.action_uid, 555001)
    assert result is not None and result.executed is True
    assert action["status"] == "executed"
    assert calls == [{"post_id": 12}]


def test_red_can_be_rejected_at_second_step(user, project):
    registry.register("social.publish", lambda payload, ctx: "sent")
    res = gateway.request_action(
        action_type="social.publish", title="انتشار پست",
        payload={}, requested_by=user["id"], chat_id=999,
    )
    gateway.approve(res.action_uid, 555001)
    action, toast = gateway.reject(res.action_uid, 555001)
    assert action["status"] == "rejected"


# ── Expiry ──────────────────────────────────────────────────────────────────

def test_expired_action_cannot_be_approved(user):
    action = repo.create_pending_action(
        action_type="budget.add_line", title="کهنه", risk="yellow",
        requested_by=user["id"], chat_id=1, ttl_seconds=-10,
    )
    with pytest.raises(gateway.DecisionError):
        gateway.approve(action["action_uid"], 555001)
    assert repo.get_pending_action(action["action_uid"])["status"] == "expired"


def test_expire_stale_actions_sweeper(user):
    repo.create_pending_action(action_type="budget.add_line", title="a",
                               risk="yellow", requested_by=user["id"], ttl_seconds=-1)
    repo.create_pending_action(action_type="budget.add_line", title="b",
                               risk="yellow", requested_by=user["id"], ttl_seconds=3600)
    assert repo.expire_stale_actions() == 1
    assert len(repo.list_pending_actions(requested_by=user["id"])) == 1


# ── Executor safety ─────────────────────────────────────────────────────────

def test_missing_executor_marks_failed_not_crash(user):
    res = gateway.request_action(
        action_type="integration.connect", title="اتصال",
        payload={}, requested_by=user["id"], chat_id=1,
    )
    action, result, toast = gateway.approve(res.action_uid, 555001)
    assert action["status"] == "failed"
    assert result is not None and result.executed is False


def test_executor_exception_is_captured(user):
    registry.register("content.generate",
                      lambda p, c: (_ for _ in ()).throw(RuntimeError("boom")))
    res = gateway.request_action(
        action_type="content.generate", title="تولید محتوا",
        payload={}, requested_by=user["id"], chat_id=1,
    )
    action, result, toast = gateway.approve(res.action_uid, 555001)
    assert action["status"] == "failed"
    assert "boom" in (action["error"] or "")


# ── callback_data round-trip ────────────────────────────────────────────────

def test_callback_data_roundtrip_and_length():
    uid = db.new_uid("act")
    data = gateway.make_callback(gateway.CB_APPROVE, uid)
    assert len(data.encode()) <= 64
    assert gateway.parse_callback(data) == (gateway.CB_APPROVE, uid)
    assert gateway.is_approval_callback(data)
    assert gateway.parse_callback("garbage") is None
    assert not gateway.is_approval_callback("other:thing:1")


def test_handle_callback_approves(user, project, monkeypatch):
    res = gateway.request_action(
        action_type="budget.add_line", title="بودجه",
        payload={"label": "seo", "amount": 100, "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )
    gateway.handle_callback({
        "callback_query_id": "cq1",
        "data": gateway.make_callback(gateway.CB_APPROVE, res.action_uid),
        "user_id": 555001, "chat_id": 999, "message_id": 4242,
    })
    assert repo.get_pending_action(res.action_uid)["status"] == "executed"
    assert len(repo.list_budget(project["id"])) == 1


def test_handle_callback_with_bad_data_does_not_raise():
    gateway.handle_callback({"callback_query_id": "cq", "data": "nonsense",
                             "user_id": 1, "chat_id": 1, "message_id": 1})


# ── Card rendering ──────────────────────────────────────────────────────────

def test_card_and_keyboard_shape(user, project):
    res = gateway.request_action(
        action_type="wordpress.publish", title="انتشار",
        payload={"post_id": 5}, requested_by=user["id"],
        project_id=project["id"], chat_id=999,
    )
    action = repo.get_pending_action(res.action_uid)
    text = gateway.render_card(action)
    assert "🔴" in text and "انتشار" in text and res.action_uid in text

    kb = gateway.build_keyboard(action)
    row = kb["inline_keyboard"][0]
    assert len(row) == 2
    assert "تأیید" in row[0]["text"] and "لغو" in row[1]["text"]
    assert row[0]["callback_data"].startswith("ap:")


def test_final_text_reflects_status(user):
    res = gateway.request_action(action_type="budget.add_line", title="b",
                                 payload={}, requested_by=user["id"], chat_id=1)
    action, _ = gateway.reject(res.action_uid, 555001)
    assert "لغو شد" in gateway.final_text(action, None)


# ── Project dossier (§2) ────────────────────────────────────────────────────

def test_project_dossier_assembles_everything(user, project):
    pid = project["id"]
    repo.add_kpi(project_id=pid, name="ترافیک ارگانیک", target_value=10000,
                 current_value=4000, unit="بازدید")
    repo.add_budget_line(project_id=pid, label="محتوا", amount=20_000_000,
                         spent=5_000_000, currency="IRT")
    repo.add_budget_line(project_id=pid, label="فروش", amount=50_000_000,
                         kind="income", currency="IRT")
    repo.add_person(project_id=pid, name="مریم", role="نویسنده")
    repo.create_task(title="مقاله جدید", project_id=pid)
    repo.record_decision(project_id=pid, problem="کدام کیورد؟", decision="گلاب")
    repo.add_memory(memory_type="fact", scope="project",
                    content="مخاطب B2B است", project_id=pid)

    d = repo.project_dossier(project)
    assert d["project"]["slug"] == "testproj"
    assert len(d["kpis"]) == 1 and len(d["people"]) == 1
    assert len(d["open_tasks"]) == 1 and len(d["decisions"]) == 1
    assert len(d["memories"]) == 1
    totals = d["budget_totals"]["IRT"]
    assert totals["planned"] == 20_000_000
    assert totals["spent"] == 5_000_000
    assert totals["income"] == 50_000_000


def test_dossier_includes_pending_actions(user, project):
    gateway.request_action(action_type="wordpress.publish", title="انتشار",
                           payload={}, requested_by=user["id"],
                           project_id=project["id"], chat_id=1)
    d = repo.project_dossier(project)
    assert len(d["pending_actions"]) == 1
    assert d["pending_actions"][0]["risk"] == "red"


def test_dossier_executors_work_through_gateway(user, project):
    for action_type, payload, checker in [
        ("kpi.add", {"name": "CTR", "target_value": 5}, lambda: repo.list_kpis(project["id"])),
        ("person.add", {"name": "رضا", "role": "سئوکار"}, lambda: repo.list_people(project["id"])),
    ]:
        res = gateway.request_action(
            action_type=action_type, title=action_type, payload=payload,
            requested_by=user["id"], project_id=project["id"], chat_id=1,
        )
        assert res.executed is True, res.error
        assert len(checker()) == 1


def test_decision_survives_telegram_outage(user, project, monkeypatch):
    """A failing answerCallbackQuery must not roll back an approved action."""
    res = gateway.request_action(
        action_type="budget.add_line", title="بودجه",
        payload={"label": "seo", "amount": 100, "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=999,
    )

    def boom(*a, **kw):
        raise RuntimeError("telegram down")

    for module in ("app.telegram.client", "app.telegram"):
        monkeypatch.setattr(f"{module}.answer_callback_query", boom)
        monkeypatch.setattr(f"{module}.edit_message_text", boom)

    gateway.handle_callback({
        "callback_query_id": "cq1",
        "data": gateway.make_callback(gateway.CB_APPROVE, res.action_uid),
        "user_id": 555001, "chat_id": 999, "message_id": 4242,
    })
    assert repo.get_pending_action(res.action_uid)["status"] == "executed"
    assert len(repo.list_budget(project["id"])) == 1


def test_red_card_step_counter_is_sane(user, project):
    """The card must never say 'step 4 of 2' after execution."""
    registry.register("wordpress.publish", lambda p, c: "ok")
    res = gateway.request_action(
        action_type="wordpress.publish", title="انتشار", payload={},
        requested_by=user["id"], project_id=project["id"], chat_id=1,
    )
    action = repo.get_pending_action(res.action_uid)
    assert "مرحله 1 از 2" in gateway.render_card(action)

    action, _, _ = gateway.approve(res.action_uid, 555001)
    assert "مرحله 2 از 2" in gateway.render_card(action)

    action, _, _ = gateway.approve(res.action_uid, 555001)
    card = gateway.render_card(action)
    # No step prompt and no countdown once the card is closed. ("دو مرحله‌ای"
    # in the risk label is fine — we assert on the prompt phrasing itself.)
    assert "تأیید مرحله" not in card
    assert "اعتبار" not in card
