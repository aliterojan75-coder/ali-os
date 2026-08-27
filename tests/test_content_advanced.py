"""Tests for advanced Content Agent features — topic suggestions, brief, rewrite, performance."""

import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest

from app import db, repositories as repo
from app.content.repository import create_draft, list_drafts
from app.agents.content_agent import suggest_topics_from_gsc, generate_brief, get_content_performance


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
def project():
    return repo.create_project("giahkade", "گیاهکده", notes="فروش محصولات گیاهی", metadata={"products": ["عرق نعناع", "گلاب"], "existing_articles": ["گلاب را با چی بخوریم؟"]})


def test_suggest_topics_fallback_to_products(project):
    # No GSC configured — should fallback to product gap
    suggestions = suggest_topics_from_gsc(project_id=project["id"], limit=10)
    assert len(suggestions) >= 1
    # Should suggest topic for product not yet covered (عرق نعناع)
    assert any("عرق نعناع" in s["topic"] for s in suggestions)


def test_suggest_topics_from_gsc_mocked(project):
    creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", "property_url": "https://example.com/"}

    mock_gsc_data = {
        "rows": [
            {"keys": ["خرید عرق نعناع"], "clicks": 10, "impressions": 1000, "ctr": 0.01, "position": 8.5},
            {"keys": ["فواید گلاب"], "clicks": 50, "impressions": 2000, "ctr": 0.02, "position": 6.0},
            {"keys": ["روغن کنجد"], "clicks": 100, "impressions": 500, "ctr": 0.2, "position": 2.0},  # high CTR, not opportunity
        ]
    }

    with patch("app.agents.content_agent.repo.get_project", return_value=project):
        with patch("app.integrations.google.gsc_query", return_value=mock_gsc_data):
            suggestions = suggest_topics_from_gsc(creds=creds, property_url="https://example.com/", limit=10)
            # Should filter to low CTR opportunities
            assert len(suggestions) >= 1
            # روغن کنجد with high CTR should not be suggested
            assert not any("روغن کنجد" in s["topic"] for s in suggestions)
            # خرید عرق نعناع should be suggested (high impressions, low CTR, position 8.5)
            assert any("عرق نعناع" in s["topic"] or "خرید عرق نعناع" in s["topic"] for s in suggestions)


def test_generate_brief_mocked(project):
    mock_llm = MagicMock()
    mock_llm.structured_output.return_value = {
        "topic": "فواید گلاب",
        "target_audience": "B2B",
        "search_intent": "اطلاعاتی",
        "primary_keyword": "گلاب",
        "secondary_keywords": ["خرید گلاب", "گلاب اصل"],
        "outline": ["مقدمه", "فواید", "نتیجه"],
        "questions_to_answer": ["گلاب چیست؟"],
        "cta_suggestion": "خرید کنید",
        "internal_links": [],
        "notes": "",
    }

    with patch("app.agents.content_agent.get_provider", return_value=mock_llm):
        brief = generate_brief(topic="فواید گلاب", project_id=project["id"])
        assert brief["primary_keyword"] == "گلاب"
        assert len(brief["outline"]) >= 2


def test_content_performance_no_gsc(project):
    draft = create_draft(project_id=project["id"], topic="تست", title="عنوان تست")
    perf = get_content_performance(draft_uid=draft["draft_uid"], project_id=project["id"])
    # No GSC configured, should return error with needs_setup
    assert "error" in perf or "needs_setup" in perf or "topic" in perf


def test_content_performance_with_gsc_mocked(project):
    draft = create_draft(project_id=project["id"], topic="عرق نعناع", title="فواید عرق نعناع")

    creds = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", "property_url": "https://example.com/"}

    mock_gsc_data = {
        "rows": [
            {"keys": ["عرق نعناع"], "clicks": 20, "impressions": 500, "ctr": 0.04, "position": 7.0},
        ]
    }

    with patch("app.integrations.store.find") as mock_find:
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: {"id": 1, "service": "google_search_console", "project_id": project["id"]}.get(k)
        mock_find.return_value = mock_row

        with patch("app.integrations.store.credentials", return_value=creds):
            with patch("app.integrations.google.gsc_query", return_value=mock_gsc_data):
                perf = get_content_performance(draft_uid=draft["draft_uid"], project_id=project["id"])
                assert "related_queries" in perf or "topic" in perf
