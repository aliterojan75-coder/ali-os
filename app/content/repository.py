"""Content drafts repository (§9)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app import db


def create_draft(
    *,
    project_id: int | None,
    topic: str,
    title: str,
    slug_en: str | None = None,
    outline: list[str] | None = None,
    content: str | None = None,
    excerpt: str | None = None,
    faq: list[dict] | None = None,
    image_prompt: str | None = None,
    cta: str | None = None,
    meta_title: str | None = None,
    meta_description: str | None = None,
    focus_keyword: str | None = None,
    canonical_url: str | None = None,
    word_count: int = 0,
    status: str = "draft",
    cannibalization: list[dict] | None = None,
    seo_score: int | None = None,
    seo_notes: str | None = None,
    created_by: int | None = None,
) -> sqlite3.Row:
    t = db.now()
    uid = db.new_uid("cnt")
    cur = db.execute(
        """INSERT INTO content_drafts
           (draft_uid, project_id, topic, title, slug_en, outline_json, content, excerpt,
            faq_json, image_prompt, cta, meta_title, meta_description, focus_keyword,
            canonical_url, word_count, status, cannibalization_json, seo_score, seo_notes,
            created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            uid, project_id, topic.strip(), title.strip(), slug_en,
            json.dumps(outline or [], ensure_ascii=False),
            content, excerpt,
            json.dumps(faq or [], ensure_ascii=False),
            image_prompt, cta, meta_title, meta_description, focus_keyword,
            canonical_url, word_count, status,
            json.dumps(cannibalization or [], ensure_ascii=False),
            seo_score, seo_notes, created_by, t, t,
        ),
    )
    return db.query_one("SELECT * FROM content_drafts WHERE id=?", (cur.lastrowid,))


def get_draft(draft_uid: str) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM content_drafts WHERE draft_uid=?", (draft_uid,))


def list_drafts(
    *,
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 30,
) -> list[sqlite3.Row]:
    sql = "SELECT d.*, p.name AS project_name, p.slug AS project_slug FROM content_drafts d LEFT JOIN projects p ON p.id=d.project_id WHERE 1=1"
    params: list[Any] = []
    if project_id is not None:
        sql += " AND d.project_id=?"
        params.append(project_id)
    if status:
        sql += " AND d.status=?"
        params.append(status)
    sql += " ORDER BY d.updated_at DESC LIMIT ?"
    params.append(limit)
    return db.query_all(sql, tuple(params))


def update_draft(draft_uid: str, **fields: Any) -> sqlite3.Row | None:
    allowed = {
        "title", "slug_en", "outline_json", "content", "excerpt", "faq_json",
        "image_prompt", "cta", "meta_title", "meta_description", "focus_keyword",
        "canonical_url", "word_count", "status", "cannibalization_json",
        "seo_score", "seo_notes", "wordpress_post_id", "wordpress_url", "project_id",
    }
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        # JSON fields handling
        if k in ("outline_json", "faq_json", "cannibalization_json") and isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        params.append(v)
    if not sets:
        return get_draft(draft_uid)
    sets.append("updated_at=?")
    params.extend([db.now(), draft_uid])
    db.execute(f"UPDATE content_drafts SET {', '.join(sets)} WHERE draft_uid=?", tuple(params))
    return get_draft(draft_uid)


def delete_draft(draft_uid: str) -> bool:
    cur = db.execute("DELETE FROM content_drafts WHERE draft_uid=?", (draft_uid,))
    return getattr(cur, "rowcount", 1) > 0


def content_stats(project_id: int | None = None) -> dict:
    params = []
    where = ""
    if project_id is not None:
        where = " WHERE project_id=?"
        params.append(project_id)

    def _count(extra: str = "", extra_params: tuple = ()):
        sql = f"SELECT COUNT(*) AS c FROM content_drafts{where}"
        if extra:
            sql += f" AND {extra}" if where else f" WHERE {extra}"
        row = db.query_one(sql, tuple(params) + extra_params)
        return row["c"] if row else 0

    total = _count()
    by_status = {}
    for st in ("draft", "pending_approval", "approved", "published", "rejected", "archived"):
        by_status[st] = _count("status=?", (st,))

    avg_words = 0
    try:
        sql = f"SELECT AVG(word_count) AS a FROM content_drafts{where}"
        row = db.query_one(sql, tuple(params))
        avg_words = int(row["a"] or 0) if row else 0
    except Exception:
        pass

    return {
        "total": total,
        "by_status": by_status,
        "avg_word_count": avg_words,
    }
