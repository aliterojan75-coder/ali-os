"""Repository functions for users, projects, tasks, decisions, memory, events,
conversations and messages.

Keeping SQL here means the Master/agents stay ORM-agnostic and the future
PostgreSQL migration is localised.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app import db
from app.logging_config import log_event

import logging
log = logging.getLogger("repo")


# ─── Users ──────────────────────────────────────────────────────────────────

def upsert_user(telegram_id: int, username: str | None, first_name: str | None) -> sqlite3.Row:
    conn = db.get_conn()
    t = db.now()
    existing = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE users SET username=?, first_name=?, last_seen_at=? WHERE id=?",
            (username, first_name, t, existing["id"]),
        )
        return conn.execute("SELECT * FROM users WHERE id=?", (existing["id"],)).fetchone()
    cur = conn.execute(
        """INSERT INTO users (telegram_id, username, first_name, role, created_at, last_seen_at)
           VALUES (?, ?, ?, 'owner', ?, ?)""",
        (telegram_id, username, first_name, t, t),
    )
    return conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()


def get_user(telegram_id: int) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))


# ─── Projects ───────────────────────────────────────────────────────────────

def list_projects(active_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM projects"
    if active_only:
        sql += " WHERE status='active'"
    sql += " ORDER BY name"
    return db.query_all(sql)


def get_project(identifier: str | int) -> sqlite3.Row | None:
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        row = db.query_one("SELECT * FROM projects WHERE id=?", (int(identifier),))
        if row:
            return row
    ident = str(identifier).lower().strip()
    return db.query_one(
        "SELECT * FROM projects WHERE lower(slug)=? OR lower(name)=?",
        (ident, ident),
    )


def create_project(slug: str, name: str, **fields: Any) -> sqlite3.Row:
    t = db.now()
    cur = db.execute(
        """INSERT INTO projects (slug, name, domain, industry, status, notes, metadata_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            slug,
            name,
            fields.get("domain"),
            fields.get("industry"),
            fields.get("status", "active"),
            fields.get("notes"),
            json.dumps(fields.get("metadata", {}), ensure_ascii=False),
            t,
            t,
        ),
    )
    return db.query_one("SELECT * FROM projects WHERE id=?", (cur.lastrowid,))


# ─── Tasks ──────────────────────────────────────────────────────────────────

VALID_TASK_STATUSES = {
    "inbox", "planned", "in_progress", "blocked",
    "waiting_approval", "done", "cancelled",
}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


def create_task(
    *,
    title: str,
    project_id: int | None = None,
    description: str | None = None,
    priority: str = "normal",
    status: str = "inbox",
    assignee: str = "Ali",
    source: str | None = None,
    expected_result: str | None = None,
    due_at: float | None = None,
) -> sqlite3.Row:
    priority = priority if priority in VALID_PRIORITIES else "normal"
    status = status if status in VALID_TASK_STATUSES else "inbox"
    t = db.now()
    uid = db.new_uid("task")
    cur = db.execute(
        """INSERT INTO tasks
           (task_uid, project_id, title, description, priority, status, assignee,
            source, expected_result, due_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, project_id, title, description, priority, status, assignee,
         source, expected_result, due_at, t, t),
    )
    return db.query_one("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,))


def list_tasks(
    *,
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    sql = "SELECT t.*, p.name AS project_name, p.slug AS project_slug FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE 1=1"
    params: list[Any] = []
    if project_id is not None:
        sql += " AND t.project_id=?"
        params.append(project_id)
    if status:
        sql += " AND t.status=?"
        params.append(status)
    else:
        sql += " AND t.status NOT IN ('done','cancelled')"
    sql += " ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.created_at DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


def get_task(task_uid: str) -> sqlite3.Row | None:
    return db.query_one(
        "SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE t.task_uid=?",
        (task_uid,),
    )


# ─── Decisions ──────────────────────────────────────────────────────────────

def record_decision(
    *,
    project_id: int | None,
    problem: str,
    evidence: str | None = None,
    options: list[Any] | None = None,
    decision: str | None = None,
    reason: str | None = None,
    impact: str | None = None,
) -> sqlite3.Row:
    t = db.now()
    cur = db.execute(
        """INSERT INTO decisions
           (project_id, problem, evidence, options_json, decision, reason, impact, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'recorded', ?)""",
        (project_id, problem, evidence,
         json.dumps(options or [], ensure_ascii=False),
         decision, reason, impact, t),
    )
    return db.query_one("SELECT * FROM decisions WHERE id=?", (cur.lastrowid,))


def list_decisions(project_id: int | None = None, limit: int = 10) -> list[sqlite3.Row]:
    sql = "SELECT d.*, p.name AS project_name FROM decisions d LEFT JOIN projects p ON p.id=d.project_id WHERE 1=1"
    params: list[Any] = []
    if project_id is not None:
        sql += " AND d.project_id=?"
        params.append(project_id)
    sql += " ORDER BY d.created_at DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


# ─── Memory ─────────────────────────────────────────────────────────────────

def add_memory(
    *,
    memory_type: str,
    scope: str,
    content: str,
    project_id: int | None = None,
    confidence: float = 0.8,
    source: str = "inference",
) -> sqlite3.Row:
    t = db.now()
    cur = db.execute(
        """INSERT INTO memories
           (memory_type, scope, project_id, content, confidence, source, created_at, last_confirmed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (memory_type, scope, project_id, content, confidence, source, t, t),
    )
    return db.query_one("SELECT * FROM memories WHERE id=?", (cur.lastrowid,))


def search_memory(
    *,
    project_id: int | None = None,
    scope: str | None = None,
    memory_type: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM memories WHERE 1=1"
    params: list[Any] = []
    if project_id is not None:
        sql += " AND project_id=?"
        params.append(project_id)
    if scope:
        sql += " AND scope=?"
        params.append(scope)
    if memory_type:
        sql += " AND memory_type=?"
        params.append(memory_type)
    sql += " ORDER BY confidence DESC, last_confirmed DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


# ─── Conversations & Messages ───────────────────────────────────────────────

def get_or_create_conversation(user_id: int, chat_id: int) -> sqlite3.Row:
    row = db.query_one(
        "SELECT * FROM conversations WHERE user_id=? ORDER BY started_at DESC LIMIT 1",
        (user_id,),
    )
    if row:
        return row
    t = db.now()
    cur = db.execute(
        "INSERT INTO conversations (user_id, chat_id, started_at) VALUES (?, ?, ?)",
        (user_id, chat_id, t),
    )
    return db.query_one("SELECT * FROM conversations WHERE id=?", (cur.lastrowid,))


def add_message(
    *,
    conversation_id: int,
    role: str,
    content: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    meta: dict | None = None,
) -> sqlite3.Row:
    t = db.now()
    cur = db.execute(
        """INSERT INTO messages (conversation_id, role, content, created_at, tokens_in, tokens_out, meta_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (conversation_id, role, content, t, tokens_in, tokens_out,
         json.dumps(meta or {}, ensure_ascii=False)),
    )
    return db.query_one("SELECT * FROM messages WHERE id=?", (cur.lastrowid,))


def recent_messages(conversation_id: int, limit: int = 10) -> list[sqlite3.Row]:
    return db.query_all(
        "SELECT * FROM (SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
        (conversation_id, limit),
    )


# ─── Events (Event Log §37) ─────────────────────────────────────────────────

def record_event(event_type: str, *, user_id: int | None = None,
                 project_id: int | None = None, payload: dict | None = None) -> None:
    db.execute(
        "INSERT INTO events (event_type, user_id, project_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_type, user_id, project_id, json.dumps(payload or {}, ensure_ascii=False), db.now()),
    )


# ─── Pending actions / Approval System (§19) ────────────────────────────────

RISK_LEVELS = ("green", "yellow", "red")
RISK_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
RISK_LABEL_FA = {"green": "کم‌خطر", "yellow": "نیازمند تأیید", "red": "پرخطر"}

PENDING_STATUSES = (
    "pending", "confirming", "approved", "rejected",
    "expired", "executed", "failed",
)
OPEN_STATUSES = ("pending", "confirming")


def create_pending_action(
    *,
    action_type: str,
    title: str,
    risk: str = "yellow",
    summary: str | None = None,
    payload: dict | None = None,
    requested_by: int | None = None,
    project_id: int | None = None,
    agent: str = "master",
    chat_id: int | None = None,
    approvals_required: int = 1,
    ttl_seconds: float | None = None,
    status: str = "pending",
) -> sqlite3.Row:
    risk = risk if risk in RISK_LEVELS else "yellow"
    t = db.now()
    uid = db.new_uid("act")
    expires_at = (t + ttl_seconds) if ttl_seconds else None
    cur = db.execute(
        """INSERT INTO pending_actions
           (action_uid, action_type, title, summary, payload_json, risk, status,
            requested_by, project_id, agent, chat_id, approvals_required,
            approvals_count, expires_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (uid, action_type, title, summary,
         json.dumps(payload or {}, ensure_ascii=False),
         risk, status, requested_by, project_id, agent, chat_id,
         max(1, int(approvals_required)), expires_at, t, t),
    )
    return db.query_one("SELECT * FROM pending_actions WHERE id=?", (cur.lastrowid,))


def get_pending_action(action_uid: str) -> sqlite3.Row | None:
    return db.query_one(
        """SELECT a.*, p.name AS project_name, p.slug AS project_slug
           FROM pending_actions a LEFT JOIN projects p ON p.id=a.project_id
           WHERE a.action_uid=?""",
        (action_uid,),
    )


def list_pending_actions(
    *,
    requested_by: int | None = None,
    project_id: int | None = None,
    status: str | None = None,
    open_only: bool = True,
    limit: int = 20,
) -> list[sqlite3.Row]:
    sql = ("SELECT a.*, p.name AS project_name, p.slug AS project_slug "
           "FROM pending_actions a LEFT JOIN projects p ON p.id=a.project_id WHERE 1=1")
    params: list[Any] = []
    if status:
        sql += " AND a.status=?"
        params.append(status)
    elif open_only:
        sql += " AND a.status IN ('pending','confirming')"
    if requested_by is not None:
        sql += " AND a.requested_by=?"
        params.append(requested_by)
    if project_id is not None:
        sql += " AND a.project_id=?"
        params.append(project_id)
    sql += (" ORDER BY CASE a.risk WHEN 'red' THEN 0 WHEN 'yellow' THEN 1 ELSE 2 END,"
            " a.created_at DESC LIMIT ?")
    params.append(limit)
    return db.query_all(sql, tuple(params))


def update_pending_action(action_uid: str, **fields: Any) -> sqlite3.Row | None:
    allowed = {
        "status", "approvals_count", "decided_by", "decided_at",
        "result_json", "error", "message_id", "chat_id", "expires_at",
    }
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key}=?")
        params.append(value)
    if not sets:
        return get_pending_action(action_uid)
    sets.append("updated_at=?")
    params.extend([db.now(), action_uid])
    db.execute(f"UPDATE pending_actions SET {', '.join(sets)} WHERE action_uid=?", tuple(params))
    return get_pending_action(action_uid)


def expire_stale_actions(now_ts: float | None = None) -> int:
    """Mark open actions whose TTL has passed as expired. Returns the count."""
    t = now_ts if now_ts is not None else db.now()
    rows = db.query_all(
        "SELECT action_uid FROM pending_actions "
        "WHERE status IN ('pending','confirming') AND expires_at IS NOT NULL AND expires_at < ?",
        (t,),
    )
    for r in rows:
        db.execute(
            "UPDATE pending_actions SET status='expired', updated_at=? WHERE action_uid=?",
            (t, r["action_uid"]),
        )
    return len(rows)


def action_payload(row: Any) -> dict:
    try:
        return json.loads(row["payload_json"] or "{}")
    except Exception:  # noqa: BLE001
        return {}


# ─── Project dossier: KPIs / budget / people (§2) ───────────────────────────

def add_kpi(*, project_id: int, name: str, target_value: float | None = None,
            current_value: float | None = None, unit: str | None = None,
            period: str = "monthly", direction: str = "up",
            notes: str | None = None) -> sqlite3.Row:
    t = db.now()
    cur = db.execute(
        """INSERT INTO project_kpis
           (project_id, name, target_value, current_value, unit, period, direction, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, name, target_value, current_value, unit, period, direction, notes, t, t),
    )
    return db.query_one("SELECT * FROM project_kpis WHERE id=?", (cur.lastrowid,))


def list_kpis(project_id: int) -> list[sqlite3.Row]:
    return db.query_all(
        "SELECT * FROM project_kpis WHERE project_id=? ORDER BY name", (project_id,)
    )


def update_kpi_value(kpi_id: int, current_value: float) -> None:
    db.execute(
        "UPDATE project_kpis SET current_value=?, updated_at=? WHERE id=?",
        (current_value, db.now(), kpi_id),
    )


def add_budget_line(*, project_id: int, label: str, amount: float,
                    category: str | None = None, currency: str = "IRT",
                    kind: str = "expense", period: str | None = None,
                    spent: float = 0, notes: str | None = None) -> sqlite3.Row:
    t = db.now()
    cur = db.execute(
        """INSERT INTO project_budget
           (project_id, label, category, amount, currency, kind, period, spent, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, label, category, amount, currency, kind, period, spent, notes, t, t),
    )
    return db.query_one("SELECT * FROM project_budget WHERE id=?", (cur.lastrowid,))


def list_budget(project_id: int) -> list[sqlite3.Row]:
    return db.query_all(
        "SELECT * FROM project_budget WHERE project_id=? ORDER BY kind, label", (project_id,)
    )


def add_person(*, project_id: int, name: str, role: str | None = None,
               contact: str | None = None, responsibility: str | None = None,
               is_internal: bool = True, notes: str | None = None) -> sqlite3.Row:
    t = db.now()
    cur = db.execute(
        """INSERT INTO project_people
           (project_id, name, role, contact, responsibility, is_internal, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, name, role, contact, responsibility, 1 if is_internal else 0, notes, t, t),
    )
    return db.query_one("SELECT * FROM project_people WHERE id=?", (cur.lastrowid,))


def list_people(project_id: int) -> list[sqlite3.Row]:
    return db.query_all(
        "SELECT * FROM project_people WHERE project_id=? ORDER BY is_internal DESC, name",
        (project_id,),
    )


def project_dossier(project: Any) -> dict:
    """Assemble the full project file (§2): identity, KPIs, budget, people,
    open tasks, recent decisions, memories and pending approvals."""
    pid = project["id"]
    try:
        metadata = json.loads(project["metadata_json"] or "{}")
    except Exception:  # noqa: BLE001
        metadata = {}
    budget = [dict(b) for b in list_budget(pid)]
    totals: dict[str, dict[str, float]] = {}
    for line in budget:
        cur = totals.setdefault(line["currency"] or "IRT",
                                {"planned": 0.0, "spent": 0.0, "income": 0.0})
        if line["kind"] == "income":
            cur["income"] += float(line["amount"] or 0)
        else:
            cur["planned"] += float(line["amount"] or 0)
            cur["spent"] += float(line["spent"] or 0)
    return {
        "project": dict(project),
        "metadata": metadata,
        "kpis": [dict(k) for k in list_kpis(pid)],
        "budget": budget,
        "budget_totals": totals,
        "people": [dict(p) for p in list_people(pid)],
        "open_tasks": [dict(t) for t in list_tasks(project_id=pid, limit=50)],
        "decisions": [dict(d) for d in list_decisions(project_id=pid, limit=5)],
        "memories": [dict(m) for m in search_memory(project_id=pid, limit=15)],
        "pending_actions": [dict(a) for a in list_pending_actions(project_id=pid, limit=10)],
    }
