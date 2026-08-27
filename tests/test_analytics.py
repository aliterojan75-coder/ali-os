"""Tests for the dashboard analytics aggregations."""
from __future__ import annotations

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
os.environ["DATABASE_PATH"] = os.path.join(
    tempfile.mkdtemp(), f"test_{uuid.uuid4().hex}.db"
)

import pytest  # noqa: E402

from app import db, repositories as repo  # noqa: E402
from app.miniapp import analytics as an  # noqa: E402

DAY = 86400


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), f"t_{uuid.uuid4().hex}.db")
    from app.config import config
    monkeypatch.setattr(config, "DATABASE_PATH", Path(path))
    db._LOCAL.conn = None
    db.init_db()
    yield
    db._LOCAL.conn = None


@pytest.fixture()
def project():
    return repo.create_project("acme", "Acme")


def _task(title, project_id, *, priority="normal", status="inbox",
          created_ago=0.0, updated_ago=None):
    t = repo.create_task(title=title, project_id=project_id, priority=priority)
    created = time.time() - created_ago
    updated = time.time() - (updated_ago if updated_ago is not None else created_ago)
    db.execute("UPDATE tasks SET status=?, created_at=?, updated_at=? WHERE id=?",
               (status, created, updated, t["id"]))
    return t


def test_trend_buckets_by_local_day(project):
    _task("a", project["id"], created_ago=0)
    _task("b", project["id"], created_ago=0)
    _task("c", project["id"], created_ago=2 * DAY)
    tr = an.task_trend(14)
    assert len(tr["created"]) == 14 and len(tr["labels"]) == 14
    assert tr["created"][-1] == 2          # today
    assert tr["created"][-3] == 1          # two days ago
    assert sum(tr["created"]) == 3


def test_trend_counts_completions_on_the_day_they_were_done(project):
    # Created 5 days ago, finished today.
    _task("x", project["id"], status="done", created_ago=5 * DAY, updated_ago=0)
    tr = an.task_trend(14)
    assert tr["created"][-6] == 1
    assert tr["done"][-1] == 1


def test_trend_ignores_tasks_outside_the_window(project):
    _task("old", project["id"], created_ago=40 * DAY)
    tr = an.task_trend(14)
    assert sum(tr["created"]) == 0


def test_heatmap_shape_and_totals(project):
    now = time.time()
    for _ in range(3):
        db.execute("INSERT INTO events (event_type,payload_json,created_at) VALUES (?,?,?)",
                   ("x", "{}", now))
    hm = an.activity_heatmap(8)
    assert len(hm["values"]) == 56          # 8 weeks × 7 days
    assert hm["values"][-1] == 3
    assert hm["total"] == 3 and hm["max"] == 3


def test_priority_breakdown_excludes_finished_and_is_ordered(project):
    _task("u", project["id"], priority="urgent")
    _task("l", project["id"], priority="low")
    _task("d", project["id"], priority="urgent", status="done")
    pb = an.priority_breakdown()
    assert [p["key"] for p in pb] == ["urgent", "low"]
    assert pb[0]["value"] == 1              # the done one is not counted


def test_velocity_compares_two_weeks(project):
    for _ in range(4):
        _task("this", project["id"], status="done", created_ago=3 * DAY, updated_ago=2 * DAY)
    for _ in range(2):
        _task("last", project["id"], status="done", created_ago=12 * DAY, updated_ago=10 * DAY)
    v = an.velocity()
    assert v["done_this_week"] == 4
    assert v["done_last_week"] == 2
    assert v["change_percent"] == 100


def test_velocity_handles_no_previous_week(project):
    _task("t", project["id"], status="done", updated_ago=DAY)
    assert an.velocity()["change_percent"] == 100
    db.execute("DELETE FROM tasks")
    assert an.velocity()["change_percent"] is None


def test_project_health_completion_and_kpi_score(project):
    pid = project["id"]
    _task("open", pid)
    _task("done1", pid, status="done")
    _task("done2", pid, status="done")
    _task("hot", pid, priority="urgent")
    repo.add_kpi(project_id=pid, name="traffic", target_value=100,
                 current_value=50, direction="up")
    repo.add_kpi(project_id=pid, name="lcp", target_value=2000,
                 current_value=4000, direction="down")
    ph = {p["slug"]: p for p in an.project_health()}["acme"]
    assert ph["open_tasks"] == 2 and ph["done_tasks"] == 2
    assert ph["hot_tasks"] == 1
    assert ph["completion"] == 50
    # up-KPI 50%, down-KPI 2000/4000 = 50% → average 50
    assert ph["kpi_score"] == 50


def test_kpi_score_is_capped_so_one_outlier_cannot_skew_it(project):
    repo.add_kpi(project_id=project["id"], name="huge", target_value=10,
                 current_value=1000, direction="up")
    ph = {p["slug"]: p for p in an.project_health()}["acme"]
    assert ph["kpi_score"] == 150          # clamped at 1.5×, not 10000%


def test_project_health_with_no_tasks_reports_none(project):
    ph = {p["slug"]: p for p in an.project_health()}["acme"]
    assert ph["completion"] is None
    assert ph["kpi_score"] is None


def test_approvals_summary_and_rate():
    u = repo.upsert_user(1, "a", "A")
    for status in ("executed", "executed", "executed", "rejected", "pending"):
        repo.create_pending_action(action_type="wordpress.publish", title="t",
                                   risk="red", requested_by=u["id"], status=status)
    s = an.approvals_summary()
    assert s["executed"] == 3 and s["rejected"] == 1 and s["pending"] == 1
    assert s["approval_rate"] == 75        # 3 of 4 decided
    assert s["by_risk"]["red"] == 5


def test_approval_rate_is_none_before_any_decision():
    u = repo.upsert_user(1, "a", "A")
    repo.create_pending_action(action_type="x.y", title="t", risk="yellow",
                               requested_by=u["id"], status="pending")
    assert an.approvals_summary()["approval_rate"] is None


def test_overview_returns_every_section(project):
    _task("a", project["id"])
    o = an.overview()
    for key in ("counts", "velocity", "trend", "heatmap", "status_breakdown",
                "priority_breakdown", "approvals", "projects", "kpis"):
        assert key in o, f"missing {key}"
    assert o["counts"]["open_tasks"] == 1


def test_overview_on_a_completely_empty_database():
    """The dashboard must render for a brand-new install."""
    o = an.overview()
    assert o["counts"]["open_tasks"] == 0
    assert sum(o["trend"]["created"]) == 0
    assert o["projects"] == []
    assert o["velocity"]["change_percent"] is None
    assert o["approvals"]["approval_rate"] is None
