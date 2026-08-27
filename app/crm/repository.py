"""CRM repository — contacts, interactions, deals.

All functions are thin wrappers around db.query_* / db.execute
so they stay ORM-agnostic and work on both SQLite and Turso.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app import db

# ── Valid values ─────────────────────────────────────────────────────────────
CONTACT_STATUSES = {"lead", "prospect", "customer", "partner", "archived"}
INTERACTION_TYPES = {"call", "meeting", "message", "note", "email"}
DEAL_STAGES = {"lead", "qualified", "proposal", "negotiation", "won", "lost"}

# ── Contacts ─────────────────────────────────────────────────────────────────

def create_contact(
    *,
    name: str,
    project_id: int | None = None,
    company: str | None = None,
    role: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    telegram: str | None = None,
    status: str = "lead",
    tags: list[str] | None = None,
    notes: str | None = None,
    source: str | None = None,
    owner: str = "Ali",
    created_by: int | None = None,
) -> sqlite3.Row:
    status = status if status in CONTACT_STATUSES else "lead"
    t = db.now()
    uid = db.new_uid("crmc")
    cur = db.execute(
        """INSERT INTO crm_contacts
           (contact_uid, project_id, name, company, role, phone, email, telegram,
            status, tags, notes, source, owner, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            uid, project_id, name.strip(), company, role, phone, email, telegram,
            status, json.dumps(tags or [], ensure_ascii=False),
            notes, source, owner, created_by, t, t,
        ),
    )
    return db.query_one("SELECT * FROM crm_contacts WHERE id=?", (cur.lastrowid,))


def get_contact(contact_uid: str) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM crm_contacts WHERE contact_uid=?", (contact_uid,))


def get_contact_by_id(cid: int) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM crm_contacts WHERE id=?", (cid,))


def list_contacts(
    *,
    project_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    sql = "SELECT c.*, p.name AS project_name, p.slug AS project_slug FROM crm_contacts c LEFT JOIN projects p ON p.id=c.project_id WHERE 1=1"
    params: list[Any] = []
    if project_id is not None:
        sql += " AND c.project_id=?"
        params.append(project_id)
    if status and status in CONTACT_STATUSES:
        sql += " AND c.status=?"
        params.append(status)
    if search:
        like = f"%{search.strip()}%"
        sql += " AND (c.name LIKE ? OR c.company LIKE ? OR c.phone LIKE ? OR c.email LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY c.updated_at DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


def update_contact(contact_uid: str, **fields: Any) -> sqlite3.Row | None:
    allowed = {"name", "company", "role", "phone", "email", "telegram", "status", "tags", "notes", "source", "owner", "project_id", "last_contact_at"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "status" and v not in CONTACT_STATUSES:
            continue
        if k == "tags":
            v = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, tuple)) else v
        sets.append(f"{k}=?")
        params.append(v)
    if not sets:
        return get_contact(contact_uid)
    sets.append("updated_at=?")
    params.extend([db.now(), contact_uid])
    db.execute(f"UPDATE crm_contacts SET {', '.join(sets)} WHERE contact_uid=?", tuple(params))
    return get_contact(contact_uid)


def delete_contact(contact_uid: str) -> bool:
    cur = db.execute("DELETE FROM crm_contacts WHERE contact_uid=?", (contact_uid,))
    return getattr(cur, "rowcount", 1) > 0


# ── Interactions ─────────────────────────────────────────────────────────────

def add_interaction(
    *,
    contact_id: int,
    summary: str,
    project_id: int | None = None,
    type: str = "note",
    content: str | None = None,
    outcome: str | None = None,
    next_action: str | None = None,
    next_follow_up_at: float | None = None,
    created_by: int | None = None,
) -> sqlite3.Row:
    ttype = type if type in INTERACTION_TYPES else "note"
    t = db.now()
    uid = db.new_uid("crmi")
    cur = db.execute(
        """INSERT INTO crm_interactions
           (interaction_uid, contact_id, project_id, type, summary, content, outcome, next_action, next_follow_up_at, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, contact_id, project_id, ttype, summary.strip(), content, outcome, next_action, next_follow_up_at, created_by, t, t),
    )
    # bump contact last_contact_at
    db.execute("UPDATE crm_contacts SET last_contact_at=?, updated_at=? WHERE id=?", (t, t, contact_id))
    return db.query_one("SELECT * FROM crm_interactions WHERE id=?", (cur.lastrowid,))


def list_interactions(
    *,
    contact_id: int | None = None,
    project_id: int | None = None,
    limit: int = 30,
) -> list[sqlite3.Row]:
    sql = "SELECT i.*, c.name AS contact_name FROM crm_interactions i LEFT JOIN crm_contacts c ON c.id=i.contact_id WHERE 1=1"
    params: list[Any] = []
    if contact_id is not None:
        sql += " AND i.contact_id=?"
        params.append(contact_id)
    if project_id is not None:
        sql += " AND i.project_id=?"
        params.append(project_id)
    sql += " ORDER BY i.created_at DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


def upcoming_followups(
    *,
    project_id: int | None = None,
    within_days: int = 7,
    overdue_only: bool = False,
    limit: int = 20,
) -> list[sqlite3.Row]:
    now = db.now()
    cutoff = now + within_days * 86400
    sql = """SELECT i.*, c.name AS contact_name, c.company, p.name AS project_name
             FROM crm_interactions i
             JOIN crm_contacts c ON c.id=i.contact_id
             LEFT JOIN projects p ON p.id=i.project_id
             WHERE i.next_follow_up_at IS NOT NULL"""
    params: list[Any] = []
    if overdue_only:
        sql += " AND i.next_follow_up_at <= ?"
        params.append(now)
    else:
        sql += " AND i.next_follow_up_at <= ?"
        params.append(cutoff)
    if project_id is not None:
        sql += " AND i.project_id=?"
        params.append(project_id)
    sql += " ORDER BY i.next_follow_up_at ASC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


# ── Deals ────────────────────────────────────────────────────────────────────

def create_deal(
    *,
    title: str,
    contact_id: int | None = None,
    project_id: int | None = None,
    amount: float = 0,
    currency: str = "IRT",
    stage: str = "lead",
    probability: int = 50,
    expected_close_at: float | None = None,
    notes: str | None = None,
    created_by: int | None = None,
) -> sqlite3.Row:
    stage = stage if stage in DEAL_STAGES else "lead"
    probability = max(0, min(100, int(probability)))
    t = db.now()
    uid = db.new_uid("crmd")
    cur = db.execute(
        """INSERT INTO crm_deals
           (deal_uid, contact_id, project_id, title, amount, currency, stage, probability, expected_close_at, notes, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, contact_id, project_id, title.strip(), amount, currency, stage, probability, expected_close_at, notes, created_by, t, t),
    )
    return db.query_one("SELECT * FROM crm_deals WHERE id=?", (cur.lastrowid,))


def get_deal(deal_uid: str) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM crm_deals WHERE deal_uid=?", (deal_uid,))


def list_deals(
    *,
    project_id: int | None = None,
    contact_id: int | None = None,
    stage: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    sql = """SELECT d.*, c.name AS contact_name, p.name AS project_name, p.slug AS project_slug
             FROM crm_deals d
             LEFT JOIN crm_contacts c ON c.id=d.contact_id
             LEFT JOIN projects p ON p.id=d.project_id
             WHERE 1=1"""
    params: list[Any] = []
    if project_id is not None:
        sql += " AND d.project_id=?"
        params.append(project_id)
    if contact_id is not None:
        sql += " AND d.contact_id=?"
        params.append(contact_id)
    if stage and stage in DEAL_STAGES:
        sql += " AND d.stage=?"
        params.append(stage)
    sql += " ORDER BY d.updated_at DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


def update_deal(deal_uid: str, **fields: Any) -> sqlite3.Row | None:
    allowed = {"title", "amount", "currency", "stage", "probability", "expected_close_at", "notes", "contact_id", "project_id"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "stage" and v not in DEAL_STAGES:
            continue
        if k == "probability":
            v = max(0, min(100, int(v)))
        sets.append(f"{k}=?")
        params.append(v)
    if not sets:
        return get_deal(deal_uid)
    sets.append("updated_at=?")
    params.extend([db.now(), deal_uid])
    db.execute(f"UPDATE crm_deals SET {', '.join(sets)} WHERE deal_uid=?", tuple(params))
    return get_deal(deal_uid)


def delete_deal(deal_uid: str) -> bool:
    cur = db.execute("DELETE FROM crm_deals WHERE deal_uid=?", (deal_uid,))
    return getattr(cur, "rowcount", 1) > 0


def crm_stats(project_id: int | None = None) -> dict:
    """Quick stats for dashboard."""
    params = []
    where = ""
    if project_id is not None:
        where = " WHERE project_id=?"
        params.append(project_id)

    def _count(table: str, extra: str = "", extra_params: tuple = ()):
        sql = f"SELECT COUNT(*) AS c FROM {table}{where}"
        if extra:
            sql += f" AND {extra}" if where else f" WHERE {extra}"
        all_params = tuple(params) + extra_params
        row = db.query_one(sql, all_params)
        return row["c"] if row else 0

    def _sum(table: str, field: str, extra: str = "", extra_params: tuple = ()):
        sql = f"SELECT COALESCE(SUM({field}),0) AS s FROM {table}{where}"
        if extra:
            sql += f" AND {extra}" if where else f" WHERE {extra}"
        all_params = tuple(params) + extra_params
        row = db.query_one(sql, all_params)
        return float(row["s"]) if row else 0.0

    contacts_total = _count("crm_contacts")
    contacts_by_status = {}
    for st in CONTACT_STATUSES:
        contacts_by_status[st] = _count("crm_contacts", "status=?", (st,))

    deals_total = _count("crm_deals")
    deals_by_stage = {}
    for st in DEAL_STAGES:
        deals_by_stage[st] = _count("crm_deals", "stage=?", (st,))

    open_deals_amount = _sum("crm_deals", "amount", "stage NOT IN ('won','lost')")
    won_amount = _sum("crm_deals", "amount", "stage='won'")

    now = db.now()
    overdue_followups = db.query_one(
        "SELECT COUNT(*) AS c FROM crm_interactions WHERE next_follow_up_at IS NOT NULL AND next_follow_up_at <= ?" + (f" AND project_id=?" if project_id else ""),
        (now, project_id) if project_id else (now,),
    )["c"]

    return {
        "contacts_total": contacts_total,
        "contacts_by_status": contacts_by_status,
        "deals_total": deals_total,
        "deals_by_stage": deals_by_stage,
        "open_deals_amount": open_deals_amount,
        "won_amount": won_amount,
        "overdue_followups": overdue_followups,
    }
