"""Tests for Content Agent (§9) and SEO Agent (§8)."""

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.pop("TURSO_DATABASE_URL", None)

import pytest

from app import db, repositories as repo
from app.content.repository import create_draft, get_draft, list_drafts, update_draft, delete_draft, content_stats
from app.agents.content_agent import check_cannibalization
from app.agents.seo_agent import audit_content, quick_seo_check
from app.approvals import gateway
import app.approvals.actions  # noqa: F401
import app.agents.wordpress  # noqa: F401 (ensure wp executors registered)


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


def test_create_and_list_drafts(project, user):
    d = create_draft(
        project_id=project["id"],
        topic="فواید گلاب",
        title="فواید گلاب برای پوست",
        slug_en="benefits-of-rose-water",
        content="محتوای تست " * 100,
        word_count=200,
        created_by=user["id"],
    )
    assert d["draft_uid"].startswith("cnt_")
    assert d["title"] == "فواید گلاب برای پوست"

    listed = list_drafts(project_id=project["id"])
    assert len(listed) == 1

    stats = content_stats(project_id=project["id"])
    assert stats["total"] == 1
    assert stats["by_status"]["draft"] == 1


def test_update_and_delete_draft(project):
    d = create_draft(project_id=project["id"], topic="تست", title="عنوان تست")
    updated = update_draft(d["draft_uid"], status="approved", seo_score=85)
    assert updated["status"] == "approved"
    assert updated["seo_score"] == 85

    ok = delete_draft(d["draft_uid"])
    assert ok is True
    assert get_draft(d["draft_uid"]) is None


def test_cannibalization_detection(project):
    create_draft(project_id=project["id"], topic="گلاب", title="گلاب را با چی بخوریم؟")
    create_draft(project_id=project["id"], topic="عرق نعناع", title="عرق نعناع را با چی بخوریم؟")

    # Similar title should be detected
    similar = check_cannibalization(project["id"], "گلاب را با چی بخوریم بهترین ترکیب")
    assert len(similar) >= 1
    assert similar[0]["similarity"] > 0.3

    # Unrelated should not
    unrelated = check_cannibalization(project["id"], "تعمیر یخچال در قم")
    assert len(unrelated) == 0


def test_seo_audit(project):
    d = create_draft(
        project_id=project["id"],
        topic="فواید گلاب",
        title="فواید گلاب برای پوست و مو",
        slug_en="rose-water-benefits",
        content="گلاب برای پوست بسیار مفید است. " * 200,  # ~1000 words
        excerpt="چکیده",
        meta_title="فواید گلاب برای پوست — گیاهکده",
        meta_description="در این مقاله به فواید گلاب برای پوست و مو می‌پردازیم. گلاب طبیعی و اصل را از گیاهکده بخرید.",
        focus_keyword="گلاب",
        word_count=1000,
    )

    audit = audit_content(d["draft_uid"])
    assert audit["score"] >= 0
    assert audit["score"] <= 100
    assert audit["word_count"] >= 500
    assert audit["has_meta_title"] is True
    assert audit["has_focus_keyword"] is True

    # Check draft updated with seo_score
    fresh = get_draft(d["draft_uid"])
    assert fresh["seo_score"] is not None


def test_quick_seo_check():
    result = quick_seo_check(
        title="فواید گلاب",
        content="گلاب " * 100,
        meta_title="فواید گلاب برای پوست",
        focus_keyword="گلاب",
    )
    assert result["score"] <= 100
    assert result["word_count"] == 100


def test_content_approval_flow(project, user):
    # content.generate is yellow — requires approval
    res = gateway.request_action(
        action_type="content.generate",
        title="تولید محتوا: فواید عرق نعناع",
        payload={"topic": "فواید عرق نعناع", "project_id": project["id"], "created_by": user["id"]},
        requested_by=user["id"],
        project_id=project["id"],
        chat_id=999,
    )
    assert res.executed is False
    assert res.risk == "yellow"

    # Approve — will try LLM, but we have no real LLM key in test, so it will use fallback
    # Mock LLM provider to avoid network
    from unittest.mock import MagicMock

    mock_provider = MagicMock()
    mock_provider.structured_output.return_value = {
        "title": "فواید عرق نعناع برای گوارش",
        "slug_en": "mint-water-benefits",
        "outline": ["مقدمه", "فواید", "نتیجه"],
        "content": "عرق نعناع برای گوارش مفید است. " * 100,
        "excerpt": "چکیده",
        "faq": [{"q": "عرق نعناع چیست؟", "a": "نوشیدنی گیاهی"}],
        "image_prompt": "mint water",
        "cta": "خرید کنید",
        "meta_title": "فواید عرق نعناع",
        "meta_description": "توضیحات",
        "focus_keyword": "عرق نعناع",
        "word_count": 500,
    }

    # Patch get_provider
    import app.agents.content_agent as ca_module
    original_get_provider = ca_module.get_provider
    ca_module.get_provider = lambda: mock_provider

    try:
        action, result, toast = gateway.approve(res.action_uid, 555001)
        assert result is not None
        assert result.executed is True
        # Draft should be created
        drafts = list_drafts(project_id=project["id"])
        assert len(drafts) == 1
        assert "عرق نعناع" in drafts[0]["title"]
    finally:
        ca_module.get_provider = original_get_provider
