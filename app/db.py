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

-- ─── Phase 2: CRM (§14) + Notifications (§18) + PM Agent (§11) ───────────────
CREATE TABLE IF NOT EXISTS crm_contacts (
    id              INTEGER PRIMARY KEY,
    contact_uid     TEXT UNIQUE NOT NULL,
    project_id      INTEGER REFERENCES projects(id),
    name            TEXT NOT NULL,
    company         TEXT,
    role            TEXT,
    phone           TEXT,
    email           TEXT,
    telegram        TEXT,
    status          TEXT DEFAULT 'lead',  -- lead | prospect | customer | partner | archived
    tags            TEXT DEFAULT '[]',
    notes           TEXT,
    source          TEXT,
    owner           TEXT DEFAULT 'Ali',
    created_by      INTEGER REFERENCES users(id),
    last_contact_at REAL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS crm_interactions (
    id                  INTEGER PRIMARY KEY,
    interaction_uid     TEXT UNIQUE NOT NULL,
    contact_id          INTEGER NOT NULL REFERENCES crm_contacts(id) ON DELETE CASCADE,
    project_id          INTEGER REFERENCES projects(id),
    type                TEXT NOT NULL DEFAULT 'note',  -- call | meeting | message | note | email
    summary             TEXT NOT NULL,
    content             TEXT,
    outcome             TEXT,
    next_action         TEXT,
    next_follow_up_at   REAL,
    created_by          INTEGER REFERENCES users(id),
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS crm_deals (
    id                  INTEGER PRIMARY KEY,
    deal_uid            TEXT UNIQUE NOT NULL,
    contact_id          INTEGER REFERENCES crm_contacts(id) ON DELETE SET NULL,
    project_id          INTEGER REFERENCES projects(id),
    title               TEXT NOT NULL,
    amount              REAL DEFAULT 0,
    currency            TEXT DEFAULT 'IRT',
    stage               TEXT DEFAULT 'lead',  -- lead | qualified | proposal | negotiation | won | lost
    probability         INTEGER DEFAULT 50,
    expected_close_at   REAL,
    notes               TEXT,
    created_by          INTEGER REFERENCES users(id),
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id                  INTEGER PRIMARY KEY,
    notification_uid    TEXT UNIQUE NOT NULL,
    user_id             INTEGER REFERENCES users(id),
    type                TEXT NOT NULL,  -- overdue_task | approval_expiring | crm_followup | hot_task | deal_closing | etc
    title               TEXT NOT NULL,
    body                TEXT,
    related_type        TEXT,
    related_id          TEXT,
    is_read             INTEGER DEFAULT 0,
    created_at          REAL NOT NULL
);

-- ─── Phase 3: Content Agent (§9) + SEO Agent (§8) ───────────────────────────
CREATE TABLE IF NOT EXISTS content_drafts (
    id                  INTEGER PRIMARY KEY,
    draft_uid           TEXT UNIQUE NOT NULL,
    project_id          INTEGER REFERENCES projects(id),
    topic               TEXT NOT NULL,
    title               TEXT NOT NULL,
    slug_en             TEXT,
    outline_json        TEXT DEFAULT '[]',
    content             TEXT,
    excerpt             TEXT,
    faq_json            TEXT DEFAULT '[]',
    image_prompt        TEXT,
    cta                 TEXT,
    meta_title          TEXT,
    meta_description    TEXT,
    focus_keyword       TEXT,
    canonical_url       TEXT,
    word_count          INTEGER DEFAULT 0,
    status              TEXT DEFAULT 'draft',  -- draft | pending_approval | approved | published | rejected | archived
    cannibalization_json TEXT DEFAULT '[]',
    seo_score           INTEGER,
    seo_notes           TEXT,
    wordpress_post_id   INTEGER,
    wordpress_url       TEXT,
    created_by          INTEGER REFERENCES users(id),
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS seo_audits (
    id                  INTEGER PRIMARY KEY,
    audit_uid           TEXT UNIQUE NOT NULL,
    project_id          INTEGER REFERENCES projects(id),
    url                 TEXT,
    post_id             INTEGER,
    title               TEXT,
    focus_keyword       TEXT,
    score               INTEGER,
    issues_json         TEXT DEFAULT '[]',
    suggestions_json    TEXT DEFAULT '[]',
    content_length      INTEGER,
    has_meta_title      INTEGER DEFAULT 0,
    has_meta_desc       INTEGER DEFAULT 0,
    has_canonical       INTEGER DEFAULT 0,
    has_focus_keyword   INTEGER DEFAULT 0,
    cannibalization_risk INTEGER DEFAULT 0,
    created_at          REAL NOT NULL
);

-- ─── Financial: Monthly recurring income tracking (redefined §15) ──────────
-- Each project has a monthly contract; track paid/unpaid per Jalali month
CREATE TABLE IF NOT EXISTS project_incomes (
    id                  INTEGER PRIMARY KEY,
    income_uid          TEXT UNIQUE NOT NULL,
    project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    amount              REAL NOT NULL DEFAULT 0,
    currency            TEXT DEFAULT 'IRT',
    month_jalali        TEXT NOT NULL,  -- e.g., '1404-06' (YYYY-MM)
    month_gregorian     TEXT,           -- e.g., '2025-08'
    due_at              REAL,           -- when payment is due (timestamp)
    paid_at             REAL,           -- when actually paid
    status              TEXT DEFAULT 'pending',  -- pending | paid | overdue | cancelled | partial
    payment_method      TEXT,           -- e.g., کارت به کارت، واریز بانکی
    transaction_ref     TEXT,
    notes               TEXT,
    created_by          INTEGER REFERENCES users(id),
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    UNIQUE(project_id, month_jalali)
);

CREATE TABLE IF NOT EXISTS gsc_daily_stats (
    id                  INTEGER PRIMARY KEY,
    project_id          INTEGER REFERENCES projects(id),
    property_url        TEXT NOT NULL,
    date                TEXT NOT NULL,  -- YYYY-MM-DD Gregorian
    date_jalali         TEXT,           -- YYYY-MM-DD Jalali
    clicks              INTEGER DEFAULT 0,
    impressions         INTEGER DEFAULT 0,
    ctr                 REAL DEFAULT 0,
    position            REAL DEFAULT 0,
    queries_json        TEXT DEFAULT '[]',
    pages_json          TEXT DEFAULT '[]',
    created_at          REAL NOT NULL,
    UNIQUE(property_url, date)
);

CREATE TABLE IF NOT EXISTS ga4_daily_stats (
    id                  INTEGER PRIMARY KEY,
    project_id          INTEGER REFERENCES projects(id),
    property_id         TEXT NOT NULL,
    date                TEXT NOT NULL,
    date_jalali         TEXT,
    sessions            INTEGER DEFAULT 0,
    users               INTEGER DEFAULT 0,
    pageviews           INTEGER DEFAULT 0,
    conversions         INTEGER DEFAULT 0,
    bounce_rate         REAL DEFAULT 0,
    channels_json       TEXT DEFAULT '[]',
    pages_json          TEXT DEFAULT '[]',
    created_at          REAL NOT NULL,
    UNIQUE(property_id, date)
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
CREATE INDEX IF NOT EXISTS idx_crm_contacts_project ON crm_contacts(project_id);
CREATE INDEX IF NOT EXISTS idx_crm_contacts_status ON crm_contacts(status);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_contact ON crm_interactions(contact_id);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_followup ON crm_interactions(next_follow_up_at);
CREATE INDEX IF NOT EXISTS idx_crm_deals_project ON crm_deals(project_id);
CREATE INDEX IF NOT EXISTS idx_crm_deals_stage ON crm_deals(stage);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_content_drafts_project ON content_drafts(project_id);
CREATE INDEX IF NOT EXISTS idx_content_drafts_status ON content_drafts(status);
CREATE INDEX IF NOT EXISTS idx_content_drafts_uid ON content_drafts(draft_uid);
CREATE INDEX IF NOT EXISTS idx_seo_audits_project ON seo_audits(project_id);
CREATE INDEX IF NOT EXISTS idx_project_incomes_project ON project_incomes(project_id);
CREATE INDEX IF NOT EXISTS idx_project_incomes_month ON project_incomes(month_jalali);
CREATE INDEX IF NOT EXISTS idx_project_incomes_status ON project_incomes(status);
CREATE INDEX IF NOT EXISTS idx_gsc_daily_property ON gsc_daily_stats(property_url);
CREATE INDEX IF NOT EXISTS idx_gsc_daily_date ON gsc_daily_stats(date);
CREATE INDEX IF NOT EXISTS idx_ga4_daily_property ON ga4_daily_stats(property_id);
CREATE INDEX IF NOT EXISTS idx_ga4_daily_date ON ga4_daily_stats(date);
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
