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


# ── Approval System (§19) ───────────────────────────────────────────────────

@api.get("/approvals")
def approvals_list():
    repo.expire_stale_actions()
    status = request.args.get("status")
    open_only = request.args.get("all") != "1"
    limit = min(int(request.args.get("limit", 30)), 200)
    items = _rows(repo.list_pending_actions(
        status=status, open_only=open_only, limit=limit
    ))
    for a in items:
        try:
            a["payload"] = json.loads(a.get("payload_json") or "{}")
        except Exception:  # noqa: BLE001
            a["payload"] = {}
    return jsonify({"ok": True, "approvals": items})


@api.post("/approvals/<action_uid>/<decision>")
def approvals_decide(action_uid: str, decision: str):
    from app import approvals as ap

    if decision not in ("approve", "reject"):
        return jsonify({"ok": False, "error": "decision must be approve|reject"}), 400
    telegram_id = (g.telegram_user or {}).get("id")
    try:
        if decision == "approve":
            action, result, toast = ap.approve(action_uid, telegram_id)
            payload = {"executed": result.executed if result else False,
                       "result": result.result if result else None}
        else:
            action, toast = ap.reject(action_uid, telegram_id)
            payload = {"executed": False}
    except ap.DecisionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "message": toast, "action": _row(action), **payload})


# ── Full project dossier (§2) ───────────────────────────────────────────────

@api.get("/projects/<slug>/dossier")
def project_dossier(slug: str):
    project = repo.get_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "project not found"}), 404
    return jsonify({"ok": True, "dossier": repo.project_dossier(project)})


@api.post("/projects/<slug>/kpis")
def add_project_kpi(slug: str):
    project = repo.get_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "project not found"}), 404
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    kpi = repo.add_kpi(
        project_id=project["id"], name=name,
        target_value=body.get("target_value"), current_value=body.get("current_value"),
        unit=body.get("unit"), period=body.get("period", "monthly"),
        direction=body.get("direction", "up"), notes=body.get("notes"),
    )
    return jsonify({"ok": True, "kpi": _row(kpi)})


@api.post("/projects/<slug>/people")
def add_project_person(slug: str):
    project = repo.get_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "project not found"}), 404
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    person = repo.add_person(
        project_id=project["id"], name=name, role=body.get("role"),
        contact=body.get("contact"), responsibility=body.get("responsibility"),
        is_internal=bool(body.get("is_internal", True)), notes=body.get("notes"),
    )
    return jsonify({"ok": True, "person": _row(person)})


@api.post("/projects/<slug>/budget")
def add_project_budget(slug: str):
    project = repo.get_project(slug)
    if project is None:
        return jsonify({"ok": False, "error": "project not found"}), 404
    body = request.get_json(silent=True) or {}
    label = (body.get("label") or "").strip()
    if not label:
        return jsonify({"ok": False, "error": "label is required"}), 400
    line = repo.add_budget_line(
        project_id=project["id"], label=label,
        amount=float(body.get("amount") or 0), category=body.get("category"),
        currency=body.get("currency", "IRT"), kind=body.get("kind", "expense"),
        period=body.get("period"), spent=float(body.get("spent") or 0),
        notes=body.get("notes"),
    )
    return jsonify({"ok": True, "budget_line": _row(line)})


# ── Integrations / connections (§20) ────────────────────────────────────────

@api.get("/integrations/catalog")
def integrations_catalog():
    """What can be connected + the form schema the UI renders."""
    from app.integrations import catalog, crypto

    return jsonify({
        "ok": True,
        "services": catalog.as_list(),
        "encryption_ready": crypto.is_configured(),
    })


@api.get("/integrations")
def integrations_list():
    from app.integrations import store

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    rows = store.list_all(project_id=project_id)
    return jsonify({"ok": True,
                    "integrations": [store.public_view(r) for r in rows]})


@api.post("/integrations/<service>")
def integrations_save(service: str):
    """Save (or update) credentials, then immediately test the connection."""
    from app.integrations import catalog, crypto, store, testers

    svc = catalog.get(service)
    if svc is None:
        return jsonify({"ok": False, "error": "سرویس ناشناخته"}), 404
    if not svc.available:
        return jsonify({"ok": False, "error": svc.blocked_reason}), 400
    if not crypto.is_configured():
        return jsonify({
            "ok": False,
            "error": ("ENCRYPTION_KEY روی سرور تنظیم نشده است. تا وقتی این کلید "
                      "تنظیم نشود، Ali OS از ذخیره‌ی اطلاعات محرمانه خودداری می‌کند."),
            "needs_key": True,
        }), 400

    body = request.get_json(silent=True) or {}
    project_id = None
    if svc.per_project:
        slug = body.get("project_slug")
        if not slug:
            return jsonify({"ok": False, "error": "انتخاب پروژه الزامی است"}), 400
        project = repo.get_project(slug)
        if project is None:
            return jsonify({"ok": False, "error": "پروژه پیدا نشد"}), 404
        project_id = project["id"]

    values, errors = catalog.validate(service, body.get("values") or {})

    # On edit, a blank secret means "keep the stored one" — so only complain
    # about a missing required secret when nothing is stored yet.
    existing = store.find(service, project_id)
    if existing is not None:
        known = set(store.public_view(existing)["configured_fields"])
        errors = [e for e in errors
                  if not any(f'«{f.label}»' in e and f.key in known
                             for f in svc.fields)]
    if errors:
        return jsonify({"ok": False, "error": " • ".join(errors)}), 400

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    try:
        row = store.upsert(
            service=service, values=values, project_id=project_id,
            label=body.get("label"), created_by=user["id"] if user else None,
        )
    except crypto.CryptoError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    repo.record_event("integration_saved", user_id=user["id"] if user else None,
                      project_id=project_id, payload={"service": service})

    ok, message, details = (True, "ذخیره شد.", {})
    if svc.can_test:
        ok, message, details = testers.test(service, store.credentials(service, project_id))
        store.set_status(row["id"],
                         store.STATUS_CONNECTED if ok else store.STATUS_ERROR,
                         None if ok else message)

    return jsonify({"ok": True, "connected": ok, "message": message,
                    "details": details,
                    "integration": store.public_view(store.get_by_id(row["id"]))})


@api.post("/integrations/<int:integration_id>/test")
def integrations_test(integration_id: int):
    from app.integrations import store, testers

    row = store.get_by_id(integration_id)
    if row is None:
        return jsonify({"ok": False, "error": "اتصال پیدا نشد"}), 404
    try:
        creds = store.credentials(row["service"], row["project_id"])
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400
    ok, message, details = testers.test(row["service"], creds)
    store.set_status(integration_id,
                     store.STATUS_CONNECTED if ok else store.STATUS_ERROR,
                     None if ok else message)
    return jsonify({"ok": True, "connected": ok, "message": message,
                    "details": details,
                    "integration": store.public_view(store.get_by_id(integration_id))})


@api.delete("/integrations/<int:integration_id>")
def integrations_delete(integration_id: int):
    from app.integrations import store

    row = store.get_by_id(integration_id)
    if row is None:
        return jsonify({"ok": False, "error": "اتصال پیدا نشد"}), 404
    service, project_id = row["service"], row["project_id"]
    store.delete(integration_id)
    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None
    repo.record_event("integration_removed", user_id=user["id"] if user else None,
                      project_id=project_id, payload={"service": service})
    return jsonify({"ok": True})


@api.get("/health")
def health():
    return jsonify({"ok": True, "model": config.LLM_MODEL})
