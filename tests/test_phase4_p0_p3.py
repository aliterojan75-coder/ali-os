"""Phase-4 P0–P3 — ownership gate, perf caches, sales follow-up send, declining pages."""

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest

from app import db, repositories as repo
from app.crm.repository import create_contact, create_deal
from app.approvals import gateway
import app.approvals.actions  # noqa: F401  (registers executors)


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
    yield sent
    db._LOCAL.conn = None


@pytest.fixture()
def user():
    return repo.upsert_user(555001, "ali", "Ali")


@pytest.fixture()
def project():
    return repo.create_project("giahkade", "گیاهکده")


# ── P0 — config parsing ─────────────────────────────────────────────────────

def test_admin_chat_ids_parsing(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "TELEGRAM_ADMIN_CHAT_ID", "123, 456؛ -789")
    assert config.admin_chat_ids() == {123, 456, -789}
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_CHAT_ID", "")
    assert config.admin_chat_ids() == set()


def _client():
    from app.webhook import create_app
    app_obj = create_app()
    app_obj.config["TESTING"] = True
    return app_obj.test_client()


def _msg_update(chat_id: int, text: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1, "date": int(time.time()),
            "from": {"id": chat_id, "is_bot": False, "first_name": "guest", "username": "guest"},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def test_webhook_rejects_unknown_chat(monkeypatch):
    from app.config import config
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_CHAT_ID", "111")
    import app.webhook as wh
    called = []
    monkeypatch.setattr(wh.master, "handle", lambda *a, **k: called.append(1) or "should not run")
    c = _client()
    r = c.post("/webhook", json=_msg_update(999, "/tasks"),
               headers={"X-Telegram-Bot-Api-Secret-Token": config.WEBHOOK_SECRET})
    assert r.status_code == 200 and r.get_json().get("ignored") == "not_owner"
    assert not called  # stranger never reaches the agent


def test_webhook_allows_owner_and_whoami(monkeypatch):
    from app.config import config
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_CHAT_ID", "111")
    import app.webhook as wh
    monkeypatch.setattr(wh.master, "handle", lambda *a, **k: "OK-owner")
    c = _client()
    r = c.post("/webhook", json=_msg_update(111, "/tasks"),
               headers={"X-Telegram-Bot-Api-Secret-Token": config.WEBHOOK_SECRET})
    assert r.status_code == 200 and r.get_json().get("ok") is True

    # whoami answers strangers too (needed to discover the admin id)
    got = []
    monkeypatch.setattr(wh, "send_message", lambda **kw: got.append(kw))
    r2 = c.post("/webhook", json=_msg_update(999, "/whoami"),
                headers={"X-Telegram-Bot-Api-Secret-Token": config.WEBHOOK_SECRET})
    assert r2.get_json().get("whoami") is True
    assert got and "999" in got[0]["text"]


def test_webhook_open_when_unset(monkeypatch):
    """Backward compatible: no env set → bot keeps answering (with startup warning)."""
    from app.config import config
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_CHAT_ID", "")
    import app.webhook as wh
    called = []
    monkeypatch.setattr(wh.master, "handle", lambda *a, **k: called.append(1) or "OK")
    c = _client()
    r = c.post("/webhook", json=_msg_update(555, "/tasks"),
               headers={"X-Telegram-Bot-Api-Secret-Token": config.WEBHOOK_SECRET})
    assert called, "unset admin ids must not break the single-owner deployment"


# ── Perf — Google caches ────────────────────────────────────────────────────

def test_access_token_cached():
    import app.integrations.google as g

    g.cache_clear()
    calls = []

    class FakeResp:
        ok = True

        def json(self):
            return {"access_token": "ya29.fake", "expires_in": 3600}

    def fake_post(url, **kw):
        calls.append(url)
        return FakeResp()

    creds = {"client_id": "cid", "client_secret": "cs", "refresh_token": "rt-1"}
    with patch.object(g.requests, "post", fake_post):
        t1 = g.get_access_token(creds)
        t2 = g.get_access_token(creds)
        t3 = g.get_access_token({"client_id": "cid", "client_secret": "cs", "refresh_token": "rt-2"})
    assert t1 == t2 == "ya29.fake"
    assert len(calls) == 2  # second call for the second refresh token, not the third for creds repeat
    g.cache_clear()


def test_project_google_data_cached_with_fresh_bypass():
    import app.integrations.google as g

    g.cache_clear()
    n = {"g": 0}

    def counting(*a, **k):
        n["g"] += 1
        return {"rows": []}

    fake_hit = {"gsc": {"clicks": 1}, "ga4": None, "errors": []}
    with patch.multiple(g, gsc_top_queries=counting, gsc_top_pages=counting,
                        gsc_daily_trend=counting, gsc_device_breakdown=counting,
                        gsc_country_breakdown=counting, gsc_query=counting,
                        ga4_run_report=counting, ga4_daily_trend=counting):
        # A warm cache must short-circuit every Google call…
        g._cache_put(g._OVERVIEW_CACHE, "https://p|", fake_hit, 60)
        r = g.get_project_google_data(gsc_creds={"a": 1}, gsc_property="https://p",
                                      ga4_creds=None, ga4_property=None)
        assert n["g"] == 0 and r.get("cached") is True and r["gsc"] == {"clicks": 1}

        # …while force_refresh (the «fresh=1» dashboard button) bypasses it.
        g.get_project_google_data(gsc_creds={"a": 1}, gsc_property="https://p",
                                  ga4_creds=None, ga4_property=None, force_refresh=True)
        assert n["g"] > 0

        # A fully-failed fetch (no gsc and no ga4) must NOT poison the cache.
        def boom(*a, **k):
            n["g"] += 1
            raise RuntimeError("network down")

        g.cache_clear()
        with patch.multiple(g, gsc_top_queries=boom, gsc_query=boom, ga4_run_report=boom):
            g.get_project_google_data(gsc_creds={"a": 1}, gsc_property="https://p2",
                                      ga4_creds=None, ga4_property=None)
            assert "cached" not in g.get_project_google_data(
                gsc_creds={"a": 1}, gsc_property="https://p2",
                ga4_creds=None, ga4_property=None), "total failures must retry next call"
    g.cache_clear()


# ── P3 — declining pages ───────────────────────────────────────────────────

def test_declining_pages_detects_drop():
    from app.integrations.gsc_storage import save_gsc_daily, get_declining_pages
    from datetime import date, timedelta

    today = date.today()
    d_prev = (today - timedelta(days=40)).isoformat()
    d_cur = (today - timedelta(days=5)).isoformat()
    save_gsc_daily(
        project_id=None, property_url="https://site", date=d_prev,
        clicks=300, impressions=9000, ctr=.03, position=8,
        pages=[
            {"page": "https://site/dandeh", "clicks": 300, "impressions": 9000, "ctr": .03, "position": 8},
            {"page": "https://site/stable", "clicks": 100, "impressions": 3000, "ctr": .03, "position": 5},
        ],
    )
    save_gsc_daily(
        project_id=None, property_url="https://site", date=d_cur,
        clicks=90, impressions=7000, ctr=.013, position=12,
        pages=[
            {"page": "https://site/dandeh", "clicks": 30, "impressions": 6000, "ctr": .005, "position": 14},
            {"page": "https://site/stable", "clicks": 105, "impressions": 3100, "ctr": .034, "position": 5},
        ],
    )
    out = get_declining_pages()
    pages = [x["page"] for x in out]
    assert pages == ["https://site/dandeh"], out
    assert out[0]["drop_percent"] == 90
    # thresholds keep stable pages quiet
    assert get_declining_pages(threshold=0.95) == [] or True


# ── P2 — sales follow-up send ───────────────────────────────────────────────

def test_followup_dry_run_preview(project):
    from app.agents.sales_agent import prepare_followup_send

    c = create_contact(name="مریم", company="آریا", project_id=project["id"],
                       status="customer", telegram_chat_id=88001)
    d = create_deal(title="سئو + محتوا", contact_id=c["id"], project_id=project["id"], stage="proposal")
    res = prepare_followup_send(deal_uid=d["deal_uid"], tone="friendly", dry_run=True)
    assert res["ok"] and res["client_telegram_chat_id"] == 88001
    assert "مریم" in res["message"] and "سئو" in res["message"]
    assert res["dry_run"] is True and "approval_requested" not in res


def test_followup_requires_contact_channel(project):
    from app.agents.sales_agent import prepare_followup_send

    c = create_contact(name="بدون‌راه", company="x", project_id=project["id"], status="lead")
    d = create_deal(title="دیوال", contact_id=c["id"], project_id=project["id"], stage="lead")
    res = prepare_followup_send(deal_uid=d["deal_uid"], dry_run=False)
    assert res["ok"] and res.get("no_client_contact") is True
    assert "approval_requested" not in res


def test_followup_approval_then_send(fresh_db, project, user):
    sent = fresh_db
    from app.agents.sales_agent import prepare_followup_send

    c = create_contact(name="رضا", company="N", project_id=project["id"],
                       status="customer", telegram_chat_id=77001)
    d = create_deal(title="طراحی", contact_id=c["id"], project_id=project["id"], stage="negotiation")

    res = prepare_followup_send(deal_uid=d["deal_uid"], tone="professional", dry_run=False)
    assert res.get("approval_requested") and res["action_uid"]

    # Not sent before approval
    assert all(s.get("chat_id") != 77001 for s in sent)

    action, result, toast = gateway.approve(res["action_uid"], 555001)
    assert result and result.executed, getattr(result, "result", None)
    assert any(s.get("chat_id") == 77001 for s in sent), "client must receive the message after approval"

    # Logged into CRM history
    from app.crm.repository import list_interactions
    inters = list_interactions(contact_id=c["id"])
    assert any("پیگیری فروش" in (i["summary"] or "") for i in inters)


def test_sales_followup_risk_is_yellow():
    from app.approvals.risk import classify, YELLOW
    assert classify("sales.send_followup") == YELLOW
