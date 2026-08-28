"""Phase-4 performance cache and LLM resilience tests."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest

from app import db


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), f"t_{uuid.uuid4().hex}.db")
    from app.config import config
    monkeypatch.setattr(config, "DATABASE_PATH", Path(path))
    monkeypatch.setattr(config, "ENV", "development")
    monkeypatch.setattr(config, "AUTO_SET_WEBHOOK", False)
    db._LOCAL.conn = None
    db.init_db()
    yield
    db._LOCAL.conn = None


def test_heavy_get_cache_deduplicates_and_mutation_invalidates(monkeypatch):
    from app.config import config
    from app.miniapp import api as api_mod
    from app.webhook import create_app

    api_mod.clear_heavy_get_cache()
    calls = {"n": 0}

    def fake_overview():
        calls["n"] += 1
        return {"value": calls["n"]}

    monkeypatch.setattr("app.miniapp.analytics.overview", fake_overview)
    app_obj = create_app()
    app_obj.config["TESTING"] = True
    client = app_obj.test_client()

    r1 = client.get("/api/analytics")
    r2 = client.get("/api/analytics")
    assert r1.status_code == r2.status_code == 200
    assert r1.get_json()["data"] == {"value": 1}
    assert r2.get_json()["data"] == {"value": 1}
    assert r2.headers["X-Ali-OS-Cache"] == "HIT"
    assert calls["n"] == 1

    # Any mutation clears the short-lived dashboard cache.
    client.post("/api/tasks", json={"title": "invalidate cache"})
    r3 = client.get("/api/analytics")
    assert r3.get_json()["data"] == {"value": 2}
    assert calls["n"] == 2
    api_mod.clear_heavy_get_cache()


def test_llm_retryable_cloudflare_then_fallback(monkeypatch):
    from app.config import config
    from app.llm.minimax_dahl import MiniMaxDahlProvider

    monkeypatch.setattr(config, "LLM_BASE_URL", "https://primary.example/v1")
    monkeypatch.setattr(config, "LLM_MODEL", "primary-model")
    monkeypatch.setattr(config, "LLM_BASE_URL_FALLBACK", "https://fallback.example/v1")
    monkeypatch.setattr(config, "LLM_MODEL_FALLBACK", "fallback-model")
    monkeypatch.setattr("app.llm.minimax_dahl.time.sleep", lambda s: None)

    p = MiniMaxDahlProvider()
    calls = []

    class Resp:
        def __init__(self, status, text, data=None):
            self.status_code = status
            self.text = text
            self._data = data or {}
        def json(self):
            return self._data

    def fake_post(url, **kwargs):
        calls.append((url, kwargs["json"]["model"]))
        if url.startswith("https://primary"):
            return Resp(403, "<html>Just a moment... Cloudflare cf-chl</html>")
        return Resp(200, "{}", {"choices": [{"message": {"content": "ok"}}], "usage": {}})

    monkeypatch.setattr(p._session, "post", fake_post)
    resp = p.chat([], max_tokens=5)
    assert resp.content == "ok"
    assert len([c for c in calls if c[0].startswith("https://primary")]) == 4  # initial + 3 retries
    assert calls[-1] == ("https://fallback.example/v1/chat/completions", "fallback-model")
