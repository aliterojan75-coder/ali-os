"""Tests for PM Agent — morning report and prioritization."""

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
from app.agents.pm_agent import score_task, prioritized_tasks, generate_morning_report, format_morning_report_telegram


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


def test_score_task_priority():
    now = time.time()
    base = {
        "priority": "low",
        "status": "inbox",
        "due_at": None,
        "created_at": now,
    }
    urgent = {**base, "priority": "urgent"}
    assert score_task(urgent, now_ts=now) > score_task(base, now_ts=now)


def test_score_task_overdue():
    now = time.time()
    base = {
        "priority": "normal",
        "status": "inbox",
        "due_at": None,
        "created_at": now,
    }
    overdue = {**base, "due_at": now - 86400 * 2}
    assert score_task(overdue, now_ts=now) > score_task(base, now_ts=now) + 40


def test_prioritized_tasks_order(project):
    now = time.time()
    # Create tasks with different priorities
    t1 = repo.create_task(title="low task", project_id=project["id"], priority="low")
    t2 = repo.create_task(title="urgent task", project_id=project["id"], priority="urgent")
    t3 = repo.create_task(title="overdue normal", project_id=project["id"], priority="normal", due_at=now - 86400)

    # Manually set due_at for overdue
    db.execute("UPDATE tasks SET due_at=? WHERE id=?", (now - 86400, t3["id"]))

    ranked = prioritized_tasks(project_id=project["id"], limit=10, now_ts=now)
    # Overdue normal should be high, urgent should be high, low should be last
    titles = [t["title"] for t in ranked]
    assert titles[-1] == "low task"
    assert "urgent task" in titles[:2] or "overdue normal" in titles[:2]


def test_morning_report_structure(project):
    now = time.time()
    repo.create_task(title="تسک امروز", project_id=project["id"], priority="high", due_at=now + 3600)
    repo.create_task(title="تسک معوق", project_id=project["id"], priority="normal", due_at=now - 86400)

    report = generate_morning_report(project_id=project["id"])
    assert "date" in report
    assert "jalali_str" in report["date"]
    assert "counts" in report
    assert report["counts"]["open_tasks"] == 2
    assert report["counts"]["overdue_tasks"] == 1
    assert "prioritized_tasks" in report
    assert len(report["prioritized_tasks"]) == 2

    text = format_morning_report_telegram(report)
    assert "گزارش صبحگاهی" in text
    assert "معوق" in text or "فوری" in text


def test_morning_report_empty():
    report = generate_morning_report()
    assert report["counts"]["open_tasks"] == 0
    assert report["date"]["jalali"]["year"] >= 1400
