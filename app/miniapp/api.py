"""JSON API used by the Mini App dashboard."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from flask import Blueprint, g, jsonify, request

from app import db, repositories as repo
from app.config import config
from app.logging_config import get_logger
from app.miniapp.auth import verify_init_data

log = get_logger("miniapp.api")

api = Blueprint("api", __name__, url_prefix="/api")


# ── Auth ────────────────────────────────────────────────────────────────────

@api.before_request
def _auth() -> Any:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_init_data(init_data)
    if user is None:
        # In non-production (local dev through the sandbox) allow a clearly
        # marked demo session so the UI can be developed without Telegram.
        if config.ENV != "production":
            g.telegram_user = {
                "id": 0, "first_name": "Dev", "username": "dev",
                "_dev": True,
            }
            return None
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    g.telegram_user = user
    return None


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def _rows(rs: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rs]


# ── Routes ──────────────────────────────────────────────────────────────────

@api.get("/me")
def me():
    return jsonify({"ok": True, "user": g.telegram_user, "version": config.VERSION,
                    "model": config.LLM_MODEL})


@api.get("/stats")
def stats():
    c = db.get_conn()
    open_tasks = c.execute(
        "SELECT COUNT(*) c FROM tasks WHERE status NOT IN ('done','cancelled')"
    ).fetchone()["c"]
    done_tasks = c.execute(
        "SELECT COUNT(*) c FROM tasks WHERE status='done'"
    ).fetchone()["c"]
    projects = c.execute("SELECT COUNT(*) c FROM projects WHERE status='active'").fetchone()["c"]
    decisions = c.execute("SELECT COUNT(*) c FROM decisions").fetchone()["c"]
    memories = c.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
    events = c.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    by_priority = [dict(r) for r in c.execute(
        "SELECT priority, COUNT(*) c FROM tasks WHERE status NOT IN ('done','cancelled') GROUP BY priority"
    )]
    by_project = [dict(r) for r in c.execute(
        """SELECT p.name, p.slug, COUNT(t.id) AS open_count
           FROM projects p LEFT JOIN tasks t
             ON t.project_id=p.id AND t.status NOT IN ('done','cancelled')
           GROUP BY p.id ORDER BY open_count DESC LIMIT 8"""
    )]
    return jsonify({"ok": True, "stats": {
        "open_tasks": open_tasks, "done_tasks": done_tasks,
        "active_projects": projects, "decisions": decisions,
        "memories": memories, "events": events,
        "by_priority": by_priority, "by_project": by_project,
    }})


@api.get("/projects")
def projects():
    items = _rows(repo.list_projects())
    for p in items:
        try:
            p["metadata"] = json.loads(p.get("metadata_json") or "{}")
        except Exception:  # noqa: BLE001
            p["metadata"] = {}
    return jsonify({"ok": True, "projects": items})


@api.get("/tasks")
def tasks():
    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        if p:
            project_id = p["id"]
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 50)), 200)
    items = _rows(repo.list_tasks(project_id=project_id, status=status, limit=limit))
    return jsonify({"ok": True, "tasks": items})


@api.post("/tasks")
def create_task():
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400
    project_id = None
    slug = body.get("project_slug")
    if slug:
        p = repo.get_project(slug)
        if p:
            project_id = p["id"]
    task = repo.create_task(
        title=title,
        project_id=project_id,
        description=body.get("description"),
        priority=body.get("priority", "normal"),
        status=body.get("status", "inbox"),
        assignee=body.get("assignee", "Ali"),
        source="miniapp",
    )
    db.get_conn().execute(
        "INSERT INTO events (event_type, payload_json, created_at) VALUES (?, ?, ?)",
        ("task_created_miniapp", json.dumps({"task_uid": task["task_uid"]}, ensure_ascii=False), db.now()),
    )
    return jsonify({"ok": True, "task": dict(task)})


@api.post("/tasks/<task_uid>/status")
def update_task_status(task_uid: str):
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status not in repo.VALID_TASK_STATUSES:
        return jsonify({"ok": False, "error": "invalid status"}), 400
    cur = db.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE task_uid=?",
        (new_status, db.now(), task_uid),
    )
    if cur.rowcount == 0:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True})


@api.get("/decisions")
def decisions():
    return jsonify({"ok": True, "decisions": _rows(repo.list_decisions(limit=20))})


@api.get("/memories")
def memories():
    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    items = _rows(repo.search_memory(project_id=project_id, limit=50))
    return jsonify({"ok": True, "memories": items})


@api.get("/events")
def events():
    limit = min(int(request.args.get("limit", 50)), 300)
    items = _rows(db.query_all(
        "SELECT id, event_type, payload_json, created_at FROM events ORDER BY id DESC LIMIT ?",
        (limit,),
    ))
    return jsonify({"ok": True, "events": items})


@api.get("/health")
def health():
    return jsonify({"ok": True, "model": config.LLM_MODEL})
