"""Data layer. Supports two backends transparently:

- Local SQLite (default, for development): file on disk, WAL, foreign keys.
- Turso / libSQL over HTTP (production on ephemeral PaaS): enabled when
  TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set. Schema is identical.

The repository layer only sees get_conn() / query_one / query_all / execute /
transaction — it does not care which backend is active. Migrating between
them is a matter of setting (or unsetting) two environment variables.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import config
from app.logging_config import get_logger
from app.turso import maybe_connect

log = get_logger("db")

_LOCAL = threading.local()
_turso: Any = None  # shared TursoConnection (thread-safe internally)
_turso_lock = threading.Lock()


def _connect_local() -> sqlite3.Connection:
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(config.DATABASE_PATH),
        timeout=30,
        check_same_thread=False,
        isolation_level=None,  # autocommit
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def is_turso() -> bool:
    return _turso is not None


def get_conn():
    global _turso
    if _turso is not None:
        return _turso
    # Lazy init Turso so import is cheap
    if _turso is None and maybe_connect():
        with _turso_lock:
            if _turso is None:
                _turso = maybe_connect()
                log.info("db.backend", extra={"extra_fields": {"backend": "turso"}})
                return _turso
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = _connect_local()
        _LOCAL.conn = conn
        log.info("db.backend", extra={"extra_fields": {"backend": "sqlite"}})
    return conn


@contextmanager
def transaction() -> Iterator[Any]:
    conn = get_conn()
    if is_turso():
        # HTTP pipeline auto-commits each statement; no multi-statement txn.
        yield conn
        return
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    telegram_id     INTEGER UNIQUE NOT NULL,
    username        TEXT,
    first_name      TEXT,
    role            TEXT DEFAULT 'owner',
    created_at      REAL NOT NULL,
    last_seen_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    domain          TEXT,
    industry        TEXT,
    status          TEXT DEFAULT 'active',
    notes           TEXT,
    metadata_json   TEXT DEFAULT '{}',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY,
    task_uid        TEXT UNIQUE NOT NULL,
    project_id      INTEGER REFERENCES projects(id),
    title           TEXT NOT NULL,
    description     TEXT,
    priority        TEXT DEFAULT 'normal',
    status          TEXT DEFAULT 'inbox',
    assignee        TEXT DEFAULT 'Ali',
    source          TEXT,
    expected_result TEXT,
    actual_result   TEXT,
    next_action     TEXT,
    due_at          REAL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id              INTEGER PRIMARY KEY,
    memory_type     TEXT NOT NULL,
    scope           TEXT NOT NULL,
    project_id      INTEGER REFERENCES projects(id),
    content         TEXT NOT NULL,
    confidence      REAL DEFAULT 0.8,
    source          TEXT,
    created_at      REAL NOT NULL,
    last_confirmed  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER REFERENCES projects(id),
    problem         TEXT NOT NULL,
    evidence        TEXT,
    options_json    TEXT,
    decision        TEXT,
    reason          TEXT,
    impact          TEXT,
    status          TEXT DEFAULT 'recorded',
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id),
    project_id      INTEGER REFERENCES projects(id),
    chat_id         INTEGER,
    started_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id),
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      REAL NOT NULL,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    meta_json       TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY,
    event_type      TEXT NOT NULL,
    user_id         INTEGER,
    project_id      INTEGER,
    payload_json    TEXT DEFAULT '{}',
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id              INTEGER PRIMARY KEY,
    tool_name       TEXT NOT NULL,
    status          TEXT,
    input_json      TEXT,
    output_json     TEXT,
    latency_ms      INTEGER,
    created_at      REAL NOT NULL
);

-- ─── Phase 2: Approval System (§19) ────────────────────────────────────────
-- Every 🟡/🔴 action an agent wants to perform is first written here and only
-- executed after Ali approves it in Telegram. 🟢 actions are recorded too
-- (auto_approved) so the audit trail is complete.
CREATE TABLE IF NOT EXISTS pending_actions (
    id                  INTEGER PRIMARY KEY,
    action_uid          TEXT UNIQUE NOT NULL,
    action_type         TEXT NOT NULL,
    title               TEXT NOT NULL,
    summary             TEXT,
    payload_json        TEXT DEFAULT '{}',
    risk                TEXT NOT NULL DEFAULT 'yellow',   -- green | yellow | red
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending | confirming | approved | rejected | expired | executed | failed
    requested_by        INTEGER REFERENCES users(id),
    project_id          INTEGER REFERENCES projects(id),
    agent               TEXT DEFAULT 'master',
    chat_id             INTEGER,
    message_id          INTEGER,
    approvals_required  INTEGER NOT NULL DEFAULT 1,
    approvals_count     INTEGER NOT NULL DEFAULT 0,
    decided_by          INTEGER,
    decided_at          REAL,
    result_json         TEXT,
    error               TEXT,
    expires_at          REAL,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);

-- ─── Phase 2: Full project dossier (§2) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS project_kpis (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    target_value    REAL,
    current_value   REAL,
    unit            TEXT,
    period          TEXT DEFAULT 'monthly',
    direction       TEXT DEFAULT 'up',   -- up = higher is better
    notes           TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS project_budget (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    label           TEXT NOT NULL,
    category        TEXT,
    amount          REAL NOT NULL DEFAULT 0,
    currency        TEXT DEFAULT 'IRT',
    kind            TEXT DEFAULT 'expense',  -- expense | income | allocation
    period          TEXT,
    spent           REAL DEFAULT 0,
    notes           TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS project_people (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    role            TEXT,
    contact         TEXT,
    responsibility  TEXT,
    is_internal     INTEGER DEFAULT 1,
    notes           TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

-- ─── Phase 2: Integrations / secret management (§20) ───────────────────────
-- credentials_json is Fernet-encrypted at rest and the key lives only in env.
CREATE TABLE IF NOT EXISTS integrations (
    id              INTEGER PRIMARY KEY,
    project_id      INTEGER REFERENCES projects(id),
    service         TEXT NOT NULL,
    label           TEXT,
    credentials_enc TEXT,
    public_json     TEXT DEFAULT '{}',
    status          TEXT DEFAULT 'pending',  -- pending | connected | error | disabled
    last_error      TEXT,
    last_checked_at REAL,
    created_by      INTEGER,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    UNIQUE (project_id, service)
);

CREATE INDEX IF NOT EXISTS idx_integrations_project ON integrations(project_id);
CREATE INDEX IF NOT EXISTS idx_integrations_service ON integrations(service);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_actions(status);
CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_actions(requested_by);
CREATE INDEX IF NOT EXISTS idx_kpis_project ON project_kpis(project_id);
CREATE INDEX IF NOT EXISTS idx_budget_project ON project_budget(project_id);
CREATE INDEX IF NOT EXISTS idx_people_project ON project_people(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
"""


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    backend = "turso" if is_turso() else "sqlite"
    log.info("db.initialized", extra={"extra_fields": {"backend": backend}})


# ─── Small helpers ──────────────────────────────────────────────────────────

def new_uid(prefix: str = "t") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now() -> float:
    return time.time()


def query_one(sql: str, params: tuple = ()):
    return get_conn().execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = ()):
    return get_conn().execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()):
    return get_conn().execute(sql, params)
