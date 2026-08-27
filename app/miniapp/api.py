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


@api.get("/analytics")
def analytics():
    """Everything the dashboard charts need, in a single round-trip."""
    from app.miniapp import analytics as an

    return jsonify({"ok": True, "data": an.overview()})


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



# ── PM Agent: Morning report (§11) ──────────────────────────────────────────

@api.get("/morning")
@api.get("/pm/morning")
def morning_report():
    """Morning report with Jalali calendar and smart prioritization."""
    from app.agents.pm_agent import generate_morning_report

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    report = generate_morning_report(
        user_id=user["id"] if user else None,
        project_id=project_id,
    )
    return jsonify({"ok": True, "report": report})


@api.get("/pm/prioritized")
def prioritized_tasks_api():
    from app.agents.pm_agent import prioritized_tasks

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    limit = min(int(request.args.get("limit", 20)), 100)
    tasks = prioritized_tasks(project_id=project_id, limit=limit)
    return jsonify({"ok": True, "tasks": tasks})


# ── CRM (§14) ────────────────────────────────────────────────────────────────

@api.get("/crm/contacts")
def crm_list_contacts():
    from app.crm.repository import list_contacts

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    status = request.args.get("status")
    search = request.args.get("q") or request.args.get("search")
    limit = min(int(request.args.get("limit", 50)), 200)
    rows = list_contacts(project_id=project_id, status=status, search=search, limit=limit)
    return jsonify({"ok": True, "contacts": [dict(r) for r in rows]})


@api.post("/crm/contacts")
def crm_create_contact():
    from app import approvals

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400

    project_id = None
    slug = body.get("project_slug")
    if slug:
        p = repo.get_project(slug)
        project_id = p["id"] if p else None

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="crm.create_contact",
        title=f"مخاطب جدید: {name}",
        summary=body.get("company") or body.get("notes"),
        payload={
            "name": name,
            "project_id": project_id,
            "company": body.get("company"),
            "role": body.get("role"),
            "phone": body.get("phone"),
            "email": body.get("email"),
            "telegram": body.get("telegram"),
            "status": body.get("status", "lead"),
            "tags": body.get("tags"),
            "notes": body.get("notes"),
            "source": body.get("source"),
            "owner": body.get("owner", "Ali"),
            "created_by": user["id"] if user else None,
        },
        requested_by=user["id"] if user else None,
        project_id=project_id,
        agent="miniapp",
    )
    if res.executed:
        # Fetch created contact (last one)
        from app.crm.repository import list_contacts
        contacts = list_contacts(project_id=project_id, limit=1)
        return jsonify({"ok": True, "executed": True, "contact": dict(contacts[0]) if contacts else None, "result": res.result})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "message": res.message})


@api.get("/crm/contacts/<contact_uid>")
def crm_get_contact(contact_uid: str):
    from app.crm.repository import get_contact, list_interactions, list_deals

    contact = get_contact(contact_uid)
    if not contact:
        return jsonify({"ok": False, "error": "not found"}), 404
    interactions = [dict(r) for r in list_interactions(contact_id=contact["id"], limit=30)]
    deals = [dict(r) for r in list_deals(contact_id=contact["id"], limit=20)]
    return jsonify({"ok": True, "contact": dict(contact), "interactions": interactions, "deals": deals})


@api.post("/crm/contacts/<contact_uid>")
def crm_update_contact(contact_uid: str):
    from app import approvals

    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"ok": False, "error": "no fields"}), 400

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None
    contact_payload = {"contact_uid": contact_uid}
    for k in ("name", "company", "role", "phone", "email", "telegram", "status", "tags", "notes", "source", "owner", "project_id"):
        if k in body:
            contact_payload[k] = body[k]

    res = approvals.request_action(
        action_type="crm.update_contact",
        title=f"ویرایش مخاطب: {contact_uid}",
        payload=contact_payload,
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        from app.crm.repository import get_contact
        c = get_contact(contact_uid)
        return jsonify({"ok": True, "executed": True, "contact": dict(c) if c else None})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "message": res.message})


@api.delete("/crm/contacts/<contact_uid>")
def crm_delete_contact(contact_uid: str):
    from app import approvals

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="crm.delete_contact",
        title=f"حذف مخاطب: {contact_uid}",
        payload={"contact_uid": contact_uid},
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        return jsonify({"ok": True, "executed": True})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "message": res.message})


@api.get("/crm/interactions")
def crm_list_interactions():
    from app.crm.repository import list_interactions, upcoming_followups

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    if request.args.get("upcoming") == "1":
        within = int(request.args.get("days", 7))
        overdue_only = request.args.get("overdue") == "1"
        if overdue_only:
            rows = upcoming_followups(project_id=project_id, overdue_only=True, limit=50)
        else:
            rows = upcoming_followups(project_id=project_id, within_days=within, limit=50)
        return jsonify({"ok": True, "interactions": [dict(r) for r in rows]})

    contact_id = request.args.get("contact_id")
    if contact_id:
        try:
            contact_id = int(contact_id)
        except ValueError:
            contact_id = None
    limit = min(int(request.args.get("limit", 30)), 200)
    rows = list_interactions(contact_id=contact_id, project_id=project_id, limit=limit)
    return jsonify({"ok": True, "interactions": [dict(r) for r in rows]})


@api.post("/crm/interactions")
def crm_create_interaction():
    from app import approvals
    from app.crm.repository import get_contact

    body = request.get_json(silent=True) or {}
    summary = (body.get("summary") or "").strip()
    if not summary:
        return jsonify({"ok": False, "error": "summary is required"}), 400

    contact_id = body.get("contact_id")
    contact_uid = body.get("contact_uid")
    if contact_uid and not contact_id:
        c = get_contact(contact_uid)
        if not c:
            return jsonify({"ok": False, "error": "contact not found"}), 404
        contact_id = c["id"]
    if not contact_id:
        return jsonify({"ok": False, "error": "contact_id or contact_uid required"}), 400

    project_id = None
    slug = body.get("project_slug")
    if slug:
        p = repo.get_project(slug)
        project_id = p["id"] if p else None

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="crm.add_interaction",
        title=f"تعامل جدید: {summary[:40]}",
        payload={
            "contact_id": contact_id,
            "project_id": project_id,
            "type": body.get("type", "note"),
            "summary": summary,
            "content": body.get("content"),
            "outcome": body.get("outcome"),
            "next_action": body.get("next_action"),
            "next_follow_up_at": body.get("next_follow_up_at"),
            "created_by": user["id"] if user else None,
        },
        requested_by=user["id"] if user else None,
        project_id=project_id,
        agent="miniapp",
    )
    if res.executed:
        return jsonify({"ok": True, "executed": True, "result": res.result})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.get("/crm/deals")
def crm_list_deals():
    from app.crm.repository import list_deals

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    stage = request.args.get("stage")
    contact_id = request.args.get("contact_id")
    if contact_id:
        try:
            contact_id = int(contact_id)
        except ValueError:
            contact_id = None
    limit = min(int(request.args.get("limit", 50)), 200)
    rows = list_deals(project_id=project_id, contact_id=contact_id, stage=stage, limit=limit)
    return jsonify({"ok": True, "deals": [dict(r) for r in rows]})


@api.post("/crm/deals")
def crm_create_deal():
    from app import approvals
    from app.crm.repository import get_contact

    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400

    contact_id = body.get("contact_id")
    if body.get("contact_uid") and not contact_id:
        c = get_contact(body["contact_uid"])
        if c:
            contact_id = c["id"]

    project_id = None
    slug = body.get("project_slug")
    if slug:
        p = repo.get_project(slug)
        project_id = p["id"] if p else None

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="crm.create_deal",
        title=f"معامله جدید: {title}",
        payload={
            "title": title,
            "contact_id": contact_id,
            "project_id": project_id,
            "amount": body.get("amount", 0),
            "currency": body.get("currency", "IRT"),
            "stage": body.get("stage", "lead"),
            "probability": body.get("probability", 50),
            "expected_close_at": body.get("expected_close_at"),
            "notes": body.get("notes"),
            "created_by": user["id"] if user else None,
        },
        requested_by=user["id"] if user else None,
        project_id=project_id,
        agent="miniapp",
    )
    if res.executed:
        return jsonify({"ok": True, "executed": True, "result": res.result})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.post("/crm/deals/<deal_uid>")
def crm_update_deal(deal_uid: str):
    from app import approvals

    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"ok": False, "error": "no fields"}), 400

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    # If only stage is being updated, use specific action
    action_type = "crm.update_deal"
    if set(body.keys()) <= {"stage", "probability"}:
        action_type = "crm.update_deal_stage"

    payload = {"deal_uid": deal_uid}
    payload.update(body)

    res = approvals.request_action(
        action_type=action_type,
        title=f"ویرایش معامله: {deal_uid}",
        payload=payload,
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        from app.crm.repository import get_deal
        d = get_deal(deal_uid)
        return jsonify({"ok": True, "executed": True, "deal": dict(d) if d else None})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.delete("/crm/deals/<deal_uid>")
def crm_delete_deal(deal_uid: str):
    from app import approvals

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="crm.delete_deal",
        title=f"حذف معامله: {deal_uid}",
        payload={"deal_uid": deal_uid},
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        return jsonify({"ok": True, "executed": True})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.get("/crm/stats")
def crm_stats_api():
    from app.crm.repository import crm_stats

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    stats = crm_stats(project_id=project_id)
    return jsonify({"ok": True, "stats": stats})


# ── Notifications (§18) ──────────────────────────────────────────────────────

@api.get("/notifications")
def notifications_list():
    from app.notifications.service import generate_notifications, list_persisted_notifications, get_notification_summary

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    live = generate_notifications(user_id=user["id"] if user else None, project_id=project_id, limit=100)
    persisted = list_persisted_notifications(user_id=user["id"] if user else None, limit=50)
    summary = get_notification_summary(user_id=user["id"] if user else None, project_id=project_id)

    return jsonify({"ok": True, "live": live, "persisted": persisted, "summary": summary})


@api.post("/notifications/<notification_uid>/read")
def notifications_mark_read(notification_uid: str):
    from app.notifications.service import mark_as_read

    ok = mark_as_read(notification_uid)
    if not ok:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True})


@api.post("/notifications/read-all")
def notifications_mark_all_read():
    from app.notifications.service import mark_all_read

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None
    count = mark_all_read(user_id=user["id"] if user else None)
    return jsonify({"ok": True, "marked": count})



# ── Content Agent (§9) + SEO (§8) ───────────────────────────────────────────

@api.get("/content/drafts")
def content_list_drafts():
    from app.content.repository import list_drafts

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 30)), 100)
    rows = list_drafts(project_id=project_id, status=status, limit=limit)
    return jsonify({"ok": True, "drafts": [dict(r) for r in rows]})


@api.post("/content/generate")
def content_generate_api():
    from app import approvals

    body = request.get_json(silent=True) or {}
    topic = (body.get("topic") or "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "topic is required"}), 400

    project_id = None
    slug = body.get("project_slug")
    if slug:
        p = repo.get_project(slug)
        project_id = p["id"] if p else None

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="content.generate",
        title=f"تولید محتوا: {topic[:50]}",
        payload={
            "topic": topic,
            "project_id": project_id,
            "created_by": user["id"] if user else None,
            "target_words": body.get("target_words", 2000),
        },
        requested_by=user["id"] if user else None,
        project_id=project_id,
        agent="miniapp",
    )
    if res.executed:
        from app.content.repository import list_drafts
        drafts = list_drafts(project_id=project_id, limit=1)
        return jsonify({"ok": True, "executed": True, "draft": dict(drafts[0]) if drafts else None, "result": res.result})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "message": res.message})


@api.get("/content/drafts/<draft_uid>")
def content_get_draft(draft_uid: str):
    from app.content.repository import get_draft
    import json as _json

    draft = get_draft(draft_uid)
    if not draft:
        return jsonify({"ok": False, "error": "not found"}), 404
    d = dict(draft)
    # Parse JSON fields for UI
    for field in ("outline_json", "faq_json", "cannibalization_json"):
        try:
            d[field.replace("_json", "")] = _json.loads(d.get(field) or "[]")
        except Exception:
            d[field.replace("_json", "")] = []
    return jsonify({"ok": True, "draft": d})


@api.post("/content/drafts/<draft_uid>")
def content_update_draft(draft_uid: str):
    from app import approvals

    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"ok": False, "error": "no fields"}), 400

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    payload = {"draft_uid": draft_uid}
    for k in ("title", "slug_en", "content", "excerpt", "meta_title", "meta_description", "focus_keyword", "status", "project_id"):
        if k in body:
            payload[k] = body[k]
    # Handle outline, faq as json
    if "outline" in body:
        import json as _json
        payload["outline_json"] = _json.dumps(body["outline"], ensure_ascii=False)
    if "faq" in body:
        import json as _json
        payload["faq_json"] = _json.dumps(body["faq"], ensure_ascii=False)

    res = approvals.request_action(
        action_type="content.draft_update",
        title=f"ویرایش پیش‌نویس: {draft_uid}",
        payload=payload,
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        from app.content.repository import get_draft
        d = get_draft(draft_uid)
        return jsonify({"ok": True, "executed": True, "draft": dict(d) if d else None})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.delete("/content/drafts/<draft_uid>")
def content_delete_draft(draft_uid: str):
    from app import approvals

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="content.delete_draft",
        title=f"حذف پیش‌نویس: {draft_uid}",
        payload={"draft_uid": draft_uid},
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        return jsonify({"ok": True, "executed": True})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.post("/content/drafts/<draft_uid>/publish")
def content_publish_draft_api(draft_uid: str):
    from app import approvals

    body = request.get_json(silent=True) or {}
    as_draft = body.get("as_draft", True)

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    action_type = "content.publish_draft" if as_draft else "content.publish"

    res = approvals.request_action(
        action_type=action_type,
        title=f"{'پیش‌نویس وردپرس' if as_draft else 'انتشار'}: {draft_uid}",
        payload={"draft_uid": draft_uid},
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        return jsonify({"ok": True, "executed": True, "result": res.result})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "message": res.message})


@api.post("/content/drafts/<draft_uid>/seo-audit")
def content_seo_audit_api(draft_uid: str):
    from app import approvals

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="seo.audit",
        title=f"بررسی سئو: {draft_uid}",
        payload={"draft_uid": draft_uid},
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )
    if res.executed:
        # Fetch latest audit
        from app import db
        row = db.query_one("SELECT * FROM seo_audits ORDER BY id DESC LIMIT 1")
        return jsonify({"ok": True, "executed": True, "audit": dict(row) if row else None, "result": res.result})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.get("/content/stats")
def content_stats_api():
    from app.content.repository import content_stats

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    stats = content_stats(project_id=project_id)
    return jsonify({"ok": True, "stats": stats})


@api.get("/content/cannibalization")
def content_cannibalization_api():
    from app.agents.content_agent import check_cannibalization

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    title = request.args.get("title") or request.args.get("q") or ""
    if not title:
        return jsonify({"ok": False, "error": "title is required"}), 400
    results = check_cannibalization(project_id, title)
    return jsonify({"ok": True, "results": results})


@api.get("/content/suggest-topics")
def content_suggest_topics_api():
    from app.agents.content_agent import suggest_topics_from_gsc

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    limit = min(int(request.args.get("limit", 15)), 50)

    try:
        suggestions = suggest_topics_from_gsc(project_id=project_id, limit=limit)
        return jsonify({"ok": True, "suggestions": suggestions, "count": len(suggestions)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api.get("/content/performance")
def content_performance_api():
    from app.agents.content_agent import get_content_performance

    draft_uid = request.args.get("draft_uid")
    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    try:
        perf = get_content_performance(draft_uid=draft_uid, project_id=project_id)
        return jsonify({"ok": True, "performance": perf})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api.post("/content/drafts/<draft_uid>/rewrite")
def content_rewrite_api(draft_uid: str):
    from app import approvals

    body = request.get_json(silent=True) or {}
    instructions = body.get("instructions", "بهینه‌سازی سئو و افزایش کیفیت")

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    # Use content.draft_update as green, but rewrite is more heavy — use yellow
    res = approvals.request_action(
        action_type="content.generate",
        title=f"بازنویسی محتوا: {draft_uid}",
        summary=instructions,
        payload={
            "draft_uid": draft_uid,
            "instructions": instructions,
            "project_id": body.get("project_id"),
        },
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )

    # For MVP, directly call rewrite if executed (green would execute immediately, but content.generate is yellow)
    # So we handle both cases
    if res.executed:
        try:
            from app.agents.content_agent import rewrite_for_seo
            result = rewrite_for_seo(draft_uid=draft_uid, instructions=instructions)
            return jsonify({"ok": True, "executed": True, "draft": result["draft"]})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "message": res.message})


# ── Google Integrations — GSC & GA4 (§4, §5) ─────────────────────────────────

@api.get("/google/overview")
@api.get("/projects/<slug>/google")
def google_overview_api(slug: str | None = None):
    """Fetch GSC + GA4 data for a project (or global if no slug)."""
    from app.integrations import store
    from app.integrations.google import get_project_google_data

    project_id = None
    if slug:
        p = repo.get_project(slug)
        if not p:
            return jsonify({"ok": False, "error": "project not found"}), 404
        project_id = p["id"]
    else:
        slug_q = request.args.get("project")
        if slug_q:
            p = repo.get_project(slug_q)
            project_id = p["id"] if p else None

    # Find credentials
    gsc_creds = None
    gsc_prop = None
    ga4_creds = None
    ga4_prop = None

    for pid in ([project_id] if project_id else []) + [None]:
        try:
            if not gsc_creds:
                row = store.find("google_search_console", pid)
                if row:
                    gsc_creds = store.credentials("google_search_console", pid)
                    gsc_prop = gsc_creds.get("property_url")
        except Exception:
            pass
        try:
            if not ga4_creds:
                row = store.find("google_analytics", pid)
                if row:
                    ga4_creds = store.credentials("google_analytics", pid)
                    ga4_prop = ga4_creds.get("property_id")
        except Exception:
            pass

    if not (gsc_creds or ga4_creds):
        return jsonify({"ok": False, "error": "Google integrations not configured — از تب اتصال‌ها وصل کن", "needs_setup": True}), 404

    data = get_project_google_data(
        gsc_creds=gsc_creds,
        gsc_property=gsc_prop,
        ga4_creds=ga4_creds,
        ga4_property=ga4_prop,
    )
    return jsonify({"ok": True, "google": data, "project_id": project_id})


@api.get("/google/gsc/queries")
def gsc_queries_api():
    from app.integrations import store
    from app.integrations.google import gsc_top_queries, gsc_query

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    # Find GSC creds
    creds = None
    prop = None
    for pid in ([project_id] if project_id else []) + [None]:
        try:
            row = store.find("google_search_console", pid)
            if row:
                creds = store.credentials("google_search_console", pid)
                prop = creds.get("property_url")
                break
        except Exception:
            pass

    if not creds or not prop:
        return jsonify({"ok": False, "error": "GSC not configured"}), 404

    dim = request.args.get("dimension", "query")
    limit = min(int(request.args.get("limit", 20)), 100)

    try:
        if dim == "page":
            from app.integrations.google import gsc_top_pages
            rows = gsc_top_pages(creds, prop, limit=limit)
        else:
            rows = gsc_top_queries(creds, prop, limit=limit)
        return jsonify({"ok": True, "rows": rows, "property": prop})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api.post("/google/sync")
def google_sync_api():
    """Sync GSC daily data to local storage for charts — no heavy resource usage."""
    from app.integrations import store
    from app.integrations.gsc_storage import sync_gsc_to_storage

    project_slug = request.args.get("project") or (request.get_json(silent=True) or {}).get("project_slug")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    # Find GSC creds
    creds = None
    prop = None
    for pid in ([project_id] if project_id else []) + [None]:
        try:
            row = store.find("google_search_console", pid)
            if row:
                creds = store.credentials("google_search_console", pid)
                prop = creds.get("property_url")
                if not project_id:
                    project_id = pid
                break
        except Exception:
            pass

    if not creds or not prop:
        return jsonify({"ok": False, "error": "GSC not configured"}), 404

    try:
        saved = sync_gsc_to_storage(creds=creds, property_url=prop, project_id=project_id, days=28)
        return jsonify({"ok": True, "saved": saved, "property": prop})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api.get("/google/ga4/report")
def ga4_report_api():
    from app.integrations import store
    from app.integrations.google import ga4_run_report

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    creds = None
    prop = None
    for pid in ([project_id] if project_id else []) + [None]:
        try:
            row = store.find("google_analytics", pid)
            if row:
                creds = store.credentials("google_analytics", pid)
                prop = creds.get("property_id")
                break
        except Exception:
            pass

    if not creds or not prop:
        return jsonify({"ok": False, "error": "GA4 not configured"}), 404

    metrics = request.args.get("metrics")
    dimensions = request.args.get("dimensions")
    metrics_list = metrics.split(",") if metrics else None
    dims_list = dimensions.split(",") if dimensions else None

    try:
        data = ga4_run_report(creds, prop, metrics=metrics_list, dimensions=dims_list, limit=20)
        return jsonify({"ok": True, "report": data, "property": prop})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Business Analyst (§12) + Sales Agent (§13) ──────────────────────────────

@api.get("/business/analysis")
@api.get("/projects/<slug>/business")
def business_analysis_api(slug: str | None = None):
    from app.agents.business_analyst import analyze_business

    project_id = None
    if slug:
        p = repo.get_project(slug)
        if not p:
            return jsonify({"ok": False, "error": "project not found"}), 404
        project_id = p["id"]
    else:
        slug_q = request.args.get("project")
        if slug_q:
            p = repo.get_project(slug_q)
            project_id = p["id"] if p else None

    analysis = analyze_business(project_id=project_id)
    return jsonify({"ok": True, "analysis": analysis})


@api.get("/sales/pipeline")
@api.get("/projects/<slug>/sales")
def sales_pipeline_api(slug: str | None = None):
    from app.agents.sales_agent import analyze_sales_pipeline

    project_id = None
    if slug:
        p = repo.get_project(slug)
        if not p:
            return jsonify({"ok": False, "error": "project not found"}), 404
        project_id = p["id"]
    else:
        slug_q = request.args.get("project")
        if slug_q:
            p = repo.get_project(slug_q)
            project_id = p["id"] if p else None

    pipeline = analyze_sales_pipeline(project_id=project_id)
    return jsonify({"ok": True, "pipeline": pipeline})


@api.post("/sales/followup-message")
def sales_followup_message_api():
    from app.agents.sales_agent import generate_followup_message

    body = request.get_json(silent=True) or {}
    deal_uid = body.get("deal_uid")
    contact_uid = body.get("contact_uid")
    tone = body.get("tone", "professional")

    try:
        msg = generate_followup_message(deal_uid=deal_uid, contact_uid=contact_uid, tone=tone)
        return jsonify({"ok": True, "message": msg})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


# ── Financial — Monthly Income Tracking (redefined §15) ──────────────────────

@api.get("/financial/incomes")
@api.get("/incomes")
def financial_list_incomes():
    from app.financial.repository import list_incomes

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None
    status = request.args.get("status")
    month = request.args.get("month") or request.args.get("month_jalali")
    limit = min(int(request.args.get("limit", 50)), 200)
    rows = list_incomes(project_id=project_id, status=status, month_jalali=month, limit=limit)
    return jsonify({"ok": True, "incomes": [dict(r) for r in rows]})


@api.post("/financial/incomes")
@api.post("/incomes")
def financial_create_income():
    from app import approvals

    body = request.get_json(silent=True) or {}
    project_slug = body.get("project_slug")
    project_id = body.get("project_id")

    if project_slug and not project_id:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    if not project_id:
        return jsonify({"ok": False, "error": "project_id or project_slug required"}), 400

    amount = body.get("amount")
    if amount is None:
        return jsonify({"ok": False, "error": "amount is required"}), 400

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="income.create",
        title=f"درآمد ماهانه: {project_slug or project_id} — {body.get('month_jalali') or 'ماه جاری'}",
        payload={
            "project_id": int(project_id),
            "amount": float(amount),
            "month_jalali": body.get("month_jalali"),
            "currency": body.get("currency", "IRT"),
            "due_at": body.get("due_at"),
            "status": body.get("status", "pending"),
            "payment_method": body.get("payment_method"),
            "notes": body.get("notes"),
            "created_by": user["id"] if user else None,
        },
        requested_by=user["id"] if user else None,
        project_id=int(project_id),
        agent="miniapp",
    )

    if res.executed:
        from app.financial.repository import list_incomes
        rows = list_incomes(project_id=int(project_id), limit=1)
        return jsonify({"ok": True, "executed": True, "income": dict(rows[0]) if rows else None, "result": res.result})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "message": res.message})


@api.post("/financial/incomes/<income_uid>/paid")
def financial_mark_paid(income_uid: str):
    from app import approvals

    body = request.get_json(silent=True) or {}
    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="income.mark_paid",
        title=f"ثبت پرداخت: {income_uid}",
        payload={
            "income_uid": income_uid,
            "paid_at": body.get("paid_at"),
            "payment_method": body.get("payment_method"),
            "transaction_ref": body.get("transaction_ref"),
        },
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )

    if res.executed:
        from app.financial.repository import get_income
        row = get_income(income_uid)
        return jsonify({"ok": True, "executed": True, "income": dict(row) if row else None})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.post("/financial/incomes/<income_uid>")
def financial_update_income(income_uid: str):
    from app import approvals

    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"ok": False, "error": "no fields"}), 400

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    payload = {"income_uid": income_uid}
    for k in ("amount", "currency", "month_jalali", "due_at", "status", "payment_method", "transaction_ref", "notes", "project_id"):
        if k in body:
            payload[k] = body[k]

    res = approvals.request_action(
        action_type="income.update",
        title=f"ویرایش درآمد: {income_uid}",
        payload=payload,
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )

    if res.executed:
        from app.financial.repository import get_income
        row = get_income(income_uid)
        return jsonify({"ok": True, "executed": True, "income": dict(row) if row else None})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.delete("/financial/incomes/<income_uid>")
def financial_delete_income(income_uid: str):
    from app import approvals

    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    res = approvals.request_action(
        action_type="income.delete",
        title=f"حذف درآمد: {income_uid}",
        payload={"income_uid": income_uid},
        requested_by=user["id"] if user else None,
        agent="miniapp",
    )

    if res.executed:
        return jsonify({"ok": True, "executed": True})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid})


@api.get("/financial/summary")
@api.get("/financial/monthly")
def financial_summary_api():
    from app.financial.repository import monthly_summary, project_contracts_summary

    project_slug = request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    summary = monthly_summary(project_id=project_id)
    contracts = project_contracts_summary()

    return jsonify({"ok": True, "summary": summary, "contracts": contracts})


@api.post("/financial/send-reminders")
def financial_send_reminders_api():
    """Send overdue payment reminders — with approval flow.

    Body: {project_slug?, dry_run: bool (default true), max_send: int}
    If dry_run=true, only generates messages, no actual sending.
    """
    from app.agents.financial_agent import send_overdue_reminders, format_overdue_summary_telegram

    body = request.get_json(silent=True) or {}
    project_slug = body.get("project_slug") or request.args.get("project")
    project_id = None
    if project_slug:
        p = repo.get_project(project_slug)
        project_id = p["id"] if p else None

    dry_run = body.get("dry_run", True)
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("1", "true", "yes")
    max_send = min(int(body.get("max_send", 5)), 20)

    results = send_overdue_reminders(project_id=project_id, dry_run=dry_run, max_send=max_send)

    # If not dry_run, also generate summary for owner
    summary_text = format_overdue_summary_telegram(results)

    return jsonify({"ok": True, "dry_run": dry_run, "results": results, "summary_text": summary_text})


@api.post("/financial/incomes/<income_uid>/reminder")
def financial_single_reminder_api(income_uid: str):
    from app.agents.financial_agent import generate_reminder_message
    from app import approvals

    body = request.get_json(silent=True) or {}
    template = body.get("template", "overdue")
    dry_run = body.get("dry_run", True)

    try:
        reminder = generate_reminder_message(income_uid, template=template)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404

    if dry_run:
        return jsonify({"ok": True, "dry_run": True, "reminder": reminder})

    # Actual send via approval
    telegram_id = (g.telegram_user or {}).get("id")
    user = repo.get_user(telegram_id) if telegram_id else None

    client = reminder["client"]
    res = approvals.request_action(
        action_type="financial.send_reminder",
        title=f"یادآوری پرداخت به {client['name'] if client else 'کارفرما'}",
        summary=f"مبلغ {float(reminder['income']['amount']):,.0f} بابت {reminder['income']['month_jalali']}",
        payload={
            "income_uid": income_uid,
            "client_telegram_chat_id": client.get("telegram_chat_id") if client else None,
            "client_email": client.get("email") if client else None,
            "message": reminder["message"],
            "project_id": reminder["income"]["project_id"],
        },
        requested_by=user["id"] if user else None,
        project_id=reminder["income"]["project_id"],
        agent="miniapp",
    )

    if res.executed:
        return jsonify({"ok": True, "executed": True, "result": res.result, "reminder": reminder})
    else:
        return jsonify({"ok": True, "executed": False, "action_uid": res.action_uid, "reminder": reminder})


@api.get("/health")
def health():
    return jsonify({"ok": True, "model": config.LLM_MODEL})
