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
