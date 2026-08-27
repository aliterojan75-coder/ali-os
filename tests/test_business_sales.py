"""Tests for Business Analyst (§12) and Sales Agent (§13)."""

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
from app.crm.repository import create_contact, create_deal, add_interaction
from app.agents.business_analyst import analyze_business, format_business_report_telegram
from app.agents.sales_agent import analyze_sales_pipeline, generate_followup_message, format_sales_report_telegram


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
    return repo.create_project("testproj", "پروژه تست")


def test_business_analysis_empty():
    analysis = analyze_business()
    assert "health_score" in analysis
    assert 0 <= analysis["health_score"] <= 100
    assert "insights" in analysis
    assert "recommendations" in analysis


def test_business_analysis_with_data(project):
    now = time.time()
    # Overdue task
    repo.create_task(title="معوق", project_id=project["id"], priority="urgent", due_at=now - 86400)
    db.execute("UPDATE tasks SET due_at=? WHERE title='معوق'", (now - 86400,))

    # CRM
    c = create_contact(name="مشتری", project_id=project["id"])
    add_interaction(contact_id=c["id"], project_id=project["id"], summary="پیگیری", next_follow_up_at=now - 86400)

    # Deal
    create_deal(title="معامله تست", project_id=project["id"], contact_id=c["id"], amount=100_000_000, stage="proposal")

    analysis = analyze_business(project_id=project["id"])
    assert analysis["counts"]["overdue_tasks"] >= 1
    assert len(analysis["insights"]) >= 1
    assert analysis["health_score"] < 100  # should have deductions

    text = format_business_report_telegram(analysis)
    assert "تحلیل کسب‌وکار" in text


def test_business_analysis_velocity():
    # Create done tasks this week vs last week
    now = time.time()
    p = repo.create_project("vel", "Velocity Test")
    for _ in range(5):
        t = repo.create_task(title="done now", project_id=p["id"])
        db.execute("UPDATE tasks SET status='done', updated_at=? WHERE id=?", (now - 86400, t["id"]))
    for _ in range(2):
        t = repo.create_task(title="done last", project_id=p["id"])
        db.execute("UPDATE tasks SET status='done', updated_at=? WHERE id=?", (now - 10 * 86400, t["id"]))

    analysis = analyze_business(project_id=p["id"])
    assert analysis["velocity"]["done_this_week"] == 5
    assert analysis["velocity"]["done_last_week"] == 2


def test_sales_pipeline_empty():
    pipeline = analyze_sales_pipeline()
    assert pipeline["total_deals"] == 0
    assert pipeline["pipeline_value"] == 0


def test_sales_pipeline_with_data(project):
    c = create_contact(name="مشتری", project_id=project["id"])
    create_deal(title="معامله ۱", project_id=project["id"], contact_id=c["id"], amount=50_000_000, stage="lead", probability=20)
    create_deal(title="معامله ۲", project_id=project["id"], contact_id=c["id"], amount=200_000_000, stage="negotiation", probability=80)
    create_deal(title="معامله برنده", project_id=project["id"], contact_id=c["id"], amount=100_000_000, stage="won")

    pipeline = analyze_sales_pipeline(project_id=project["id"])
    assert pipeline["total_deals"] == 3
    assert pipeline["by_stage"]["lead"] == 1
    assert pipeline["by_stage"]["negotiation"] == 1
    assert pipeline["by_stage"]["won"] == 1
    assert pipeline["pipeline_value"] == 250_000_000  # only open deals
    assert pipeline["weighted_value"] > 0

    text = format_sales_report_telegram(pipeline)
    assert "گزارش فروش" in text
    assert "Pipeline" in text or "پایپ‌لاین" in text or "معامله" in text


def test_sales_stale_and_closing(project):
    now = time.time()
    c = create_contact(name="مشتری", project_id=project["id"])
    d1 = create_deal(title="راکد", project_id=project["id"], contact_id=c["id"], amount=10_000_000, stage="proposal")
    # Make it stale (14+ days old)
    db.execute("UPDATE crm_deals SET updated_at=? WHERE id=?", (now - 20 * 86400, d1["id"]))

    d2 = create_deal(title="بستن زود", project_id=project["id"], contact_id=c["id"], amount=20_000_000, stage="negotiation", expected_close_at=now + 2 * 86400)

    pipeline = analyze_sales_pipeline(project_id=project["id"])
    assert len(pipeline["stale_deals"]) == 1
    assert pipeline["stale_deals"][0]["title"] == "راکد"
    assert len(pipeline["closing_soon"]) == 1


def test_generate_followup_message(project):
    c = create_contact(name="علی", company="Net Nova", project_id=project["id"])
    d = create_deal(title="پروژه سایت", project_id=project["id"], contact_id=c["id"], amount=50_000_000)

    msg = generate_followup_message(deal_uid=d["deal_uid"], tone="professional")
    assert "علی" in msg
    assert "پروژه سایت" in msg

    msg2 = generate_followup_message(contact_uid=c["contact_uid"], tone="friendly")
    assert "علی" in msg2
