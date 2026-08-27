"""Tests for the integrations layer (§20): encryption, storage, catalog,
connection testing and the WordPress agent.

No network: `requests` is monkeypatched.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)
os.environ["DATABASE_PATH"] = os.path.join(
    tempfile.mkdtemp(), f"test_{uuid.uuid4().hex}.db"
)

import pytest  # noqa: E402

from app import db, repositories as repo  # noqa: E402
from app.integrations import catalog, crypto, store, testers  # noqa: E402

TEST_KEY = "dGVzdC1rZXktZm9yLXVuaXQtdGVzdHMtMzJieXRlcyE="  # any passphrase works


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), f"t_{uuid.uuid4().hex}.db")
    from app.config import config
    monkeypatch.setattr(config, "DATABASE_PATH", Path(path))
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_KEY)
    db._LOCAL.conn = None
    db.init_db()
    yield
    db._LOCAL.conn = None


@pytest.fixture()
def project():
    return repo.create_project("acme", "Acme", domain="acme.ir")


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.ok = status < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# ── Encryption ──────────────────────────────────────────────────────────────

def test_roundtrip_encryption():
    token = crypto.encrypt("hunter2")
    assert token.startswith("fernet:")
    assert "hunter2" not in token
    assert crypto.decrypt(token) == "hunter2"


def test_refuses_to_encrypt_without_key(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    assert crypto.is_configured() is False
    with pytest.raises(crypto.CryptoError):
        crypto.encrypt("secret")


def test_wrong_key_is_a_clear_error(monkeypatch):
    token = crypto.encrypt("hunter2")
    monkeypatch.setenv("ENCRYPTION_KEY", "a-totally-different-key")
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(token)


def test_plaintext_legacy_value_still_readable():
    assert crypto.decrypt("legacy-plain") == "legacy-plain"


def test_mask_hides_the_secret():
    masked = crypto.mask("abcd1234wxyz")
    assert masked.endswith("wxyz")
    assert "abcd1234" not in masked


# ── Catalog validation ──────────────────────────────────────────────────────

def test_catalog_exposes_wordpress_form():
    wp = catalog.get("wordpress")
    keys = [f.key for f in wp.fields]
    assert keys == ["site_url", "username", "app_password"]
    assert catalog.secret_keys("wordpress") == {"app_password"}
    assert wp.guide, "the WordPress card must explain how to get the password"


def test_validate_reports_missing_required_fields():
    cleaned, errors = catalog.validate("wordpress", {"site_url": "https://a.ir"})
    assert cleaned == {"site_url": "https://a.ir"}
    assert len(errors) == 2


def test_validate_rejects_url_without_scheme():
    _, errors = catalog.validate("wordpress", {
        "site_url": "acme.ir", "username": "u", "app_password": "p"})
    assert any("http" in e for e in errors)


def test_blocked_services_are_marked():
    ads = catalog.get("google_ads")
    assert ads.available is False and ads.blocked_reason


# ── Store ───────────────────────────────────────────────────────────────────

def test_credentials_are_encrypted_at_rest(project):
    store.upsert(service="wordpress", project_id=project["id"], values={
        "site_url": "https://acme.ir", "username": "ali",
        "app_password": "super secret pw"})
    raw = db.query_one("SELECT credentials_enc, public_json FROM integrations")
    assert "super secret pw" not in raw["credentials_enc"]
    assert "super secret pw" not in (raw["public_json"] or "")
    # non-secret fields stay queryable in the clear
    assert json.loads(raw["public_json"])["username"] == "ali"


def test_credentials_roundtrip_for_agents(project):
    store.upsert(service="wordpress", project_id=project["id"], values={
        "site_url": "https://acme.ir", "username": "ali", "app_password": "pw"})
    creds = store.credentials("wordpress", project["id"])
    assert creds["app_password"] == "pw"


def test_public_view_never_leaks_the_secret(project):
    store.upsert(service="wordpress", project_id=project["id"], values={
        "site_url": "https://acme.ir", "username": "ali",
        "app_password": "abcd1234wxyz"})
    view = store.public_view(store.find("wordpress", project["id"]))
    assert view["values"]["app_password"].endswith("wxyz")
    assert "abcd1234" not in view["values"]["app_password"]
    assert view["values"]["username"] == "ali"


def test_upsert_merges_and_keeps_existing_secret(project):
    store.upsert(service="wordpress", project_id=project["id"], values={
        "site_url": "https://acme.ir", "username": "ali", "app_password": "pw"})
    # Edit only the URL, leaving the password field blank.
    store.upsert(service="wordpress", project_id=project["id"],
                 values={"site_url": "https://new.ir"})
    creds = store.credentials("wordpress", project["id"])
    assert creds["site_url"] == "https://new.ir"
    assert creds["app_password"] == "pw"          # preserved


def test_one_row_per_project_and_service(project):
    store.upsert(service="wordpress", project_id=project["id"],
                 values={"site_url": "https://a.ir"})
    store.upsert(service="wordpress", project_id=project["id"],
                 values={"site_url": "https://b.ir"})
    rows = db.query_all("SELECT * FROM integrations WHERE service='wordpress'")
    assert len(rows) == 1


def test_global_integration_is_deduplicated():
    """SQLite treats NULLs as distinct, so this must be handled in code."""
    store.upsert(service="smtp", project_id=None, values={"host": "a.com"})
    store.upsert(service="smtp", project_id=None, values={"host": "b.com"})
    rows = db.query_all("SELECT * FROM integrations WHERE service='smtp'")
    assert len(rows) == 1
    assert store.credentials("smtp")["host"] == "b.com"


def test_project_falls_back_to_global_connection(project):
    store.upsert(service="smtp", project_id=None, values={"host": "mail.com"})
    assert store.credentials("smtp", project["id"])["host"] == "mail.com"


def test_delete_removes_the_secret(project):
    row = store.upsert(service="wordpress", project_id=project["id"],
                       values={"site_url": "https://a.ir"})
    assert store.delete(row["id"]) is True
    assert store.find("wordpress", project["id"]) is None


def test_public_view_survives_a_rotated_key(project, monkeypatch):
    store.upsert(service="wordpress", project_id=project["id"],
                 values={"site_url": "https://a.ir", "username": "u",
                         "app_password": "pw"})
    monkeypatch.setenv("ENCRYPTION_KEY", "rotated-key-value")
    view = store.public_view(store.find("wordpress", project["id"]))
    assert view["readable"] is False       # flagged, not crashed


# ── Connection testers ──────────────────────────────────────────────────────

def test_wordpress_tester_success(monkeypatch):
    def fake_get(url, **kw):
        if url.endswith("/users/me"):
            return FakeResponse(200, {"name": "Ali", "roles": ["administrator"]})
        return FakeResponse(200, {"namespaces": ["wp/v2", "wc/v3"]})
    monkeypatch.setattr("app.integrations.testers.requests.get", fake_get)

    ok, msg, details = testers.test("wordpress", {
        "site_url": "https://acme.ir", "username": "ali", "app_password": "pw"})
    assert ok is True
    assert "Ali" in msg and "WooCommerce" in msg
    assert details["woocommerce"] is True


def test_wordpress_tester_bad_password(monkeypatch):
    monkeypatch.setattr("app.integrations.testers.requests.get",
                        lambda url, **kw: FakeResponse(401))
    ok, msg, _ = testers.test("wordpress", {
        "site_url": "https://acme.ir", "username": "ali", "app_password": "wrong"})
    assert ok is False
    assert "Application Password" in msg


def test_wordpress_tester_rest_api_missing(monkeypatch):
    monkeypatch.setattr("app.integrations.testers.requests.get",
                        lambda url, **kw: FakeResponse(404))
    ok, msg, _ = testers.test("wordpress", {
        "site_url": "https://acme.ir", "username": "a", "app_password": "p"})
    assert ok is False and "REST API" in msg


def test_wordpress_tester_warns_about_weak_role(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.testers.requests.get",
        lambda url, **kw: FakeResponse(200, {"name": "Bob", "roles": ["subscriber"]}))
    ok, msg, _ = testers.test("wordpress", {
        "site_url": "https://acme.ir", "username": "bob", "app_password": "p"})
    assert ok is True
    assert "اجازه‌ی انتشار" in msg


def test_tester_never_raises(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("kaboom")
    monkeypatch.setattr("app.integrations.testers.requests.get", boom)
    ok, msg, _ = testers.test("wordpress", {
        "site_url": "https://a.ir", "username": "u", "app_password": "p"})
    assert ok is False


def test_unknown_service_test_is_neutral():
    ok, msg, _ = testers.test("something_new", {})
    assert ok is True


# ── WordPress agent through the approval gateway ────────────────────────────

def test_wordpress_publish_is_red_and_gated(project, monkeypatch):
    from app import approvals
    from app.approvals import risk

    assert risk.classify("wordpress.publish") == risk.RED
    assert risk.classify("wordpress.create_draft") == risk.YELLOW

    store.upsert(service="wordpress", project_id=project["id"], values={
        "site_url": "https://acme.ir", "username": "ali", "app_password": "pw"})

    calls = []

    def fake_request(method, url, **kw):
        calls.append((method, url, kw.get("json")))
        return FakeResponse(200, {"id": 7, "link": "https://acme.ir/hello"})
    monkeypatch.setattr("app.agents.wordpress.requests.request", fake_request)
    for module in ("app.telegram.client", "app.telegram"):
        monkeypatch.setattr(f"{module}.send_message", lambda **kw: {"message_id": 1})
        monkeypatch.setattr(f"{module}.edit_message_text", lambda *a, **kw: {})
        monkeypatch.setattr(f"{module}.answer_callback_query", lambda *a, **kw: {})

    user = repo.upsert_user(4242, "ali", "Ali")
    res = approvals.request_action(
        action_type="wordpress.publish", title="انتشار مقاله",
        payload={"post_id": 7, "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=1,
    )
    assert res.executed is False and calls == []      # nothing published yet

    approvals.approve(res.action_uid, 4242)           # step 1
    assert calls == []                                # still nothing

    action, result, _ = approvals.approve(res.action_uid, 4242)   # step 2
    assert result.executed is True
    assert len(calls) == 1
    assert calls[0][2] == {"status": "publish"}


def test_wordpress_agent_without_connection_fails_clearly(project, monkeypatch):
    from app import approvals

    for module in ("app.telegram.client", "app.telegram"):
        monkeypatch.setattr(f"{module}.send_message", lambda **kw: {"message_id": 1})
        monkeypatch.setattr(f"{module}.edit_message_text", lambda *a, **kw: {})
        monkeypatch.setattr(f"{module}.answer_callback_query", lambda *a, **kw: {})

    user = repo.upsert_user(4242, "ali", "Ali")
    res = approvals.request_action(
        action_type="wordpress.create_draft", title="پیش‌نویس",
        payload={"title": "تست", "project_id": project["id"]},
        requested_by=user["id"], project_id=project["id"], chat_id=1,
    )
    action, result, _ = approvals.approve(res.action_uid, 4242)
    assert action["status"] == "failed"
    assert "اتصال وردپرس" in (action["error"] or "")


def test_content_index_reads_existing_titles(project, monkeypatch):
    from app.agents import wordpress

    store.upsert(service="wordpress", project_id=project["id"], values={
        "site_url": "https://acme.ir", "username": "ali", "app_password": "pw"})
    monkeypatch.setattr(
        "app.agents.wordpress.requests.request",
        lambda m, url, **kw: FakeResponse(200, [
            {"id": 1, "title": {"rendered": "گلاب"}, "slug": "golab",
             "link": "https://acme.ir/golab", "date": "2026-01-01"}]))
    index = wordpress.content_index(project["id"])
    assert index[0]["title"] == "گلاب" and index[0]["slug"] == "golab"


def test_public_view_labels_the_project(project):
    """The UI groups connections by project, so the name must be present."""
    row = store.upsert(service="wordpress", project_id=project["id"],
                       values={"site_url": "https://acme.ir"})
    view = store.public_view(store.get_by_id(row["id"]))
    assert view["project_name"] == "Acme"
