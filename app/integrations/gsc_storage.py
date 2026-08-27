"""Storage for GSC and GA4 daily stats — for charts without hitting Google API every time."""

from __future__ import annotations

import json
from typing import Any

from app import db
from app.utils.jalali import gregorian_to_jalali


def save_gsc_daily(
    *,
    project_id: int | None,
    property_url: str,
    date: str,  # YYYY-MM-DD Gregorian
    clicks: int = 0,
    impressions: int = 0,
    ctr: float = 0,
    position: float = 0,
    queries: list[dict] | None = None,
    pages: list[dict] | None = None,
) -> None:
    # Convert to Jalali
    try:
        gy, gm, gd = map(int, date.split("-"))
        jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
        date_jalali = f"{jy:04d}-{jm:02d}-{jd:02d}"
    except Exception:
        date_jalali = ""

    t = db.now()
    # Upsert (INSERT OR REPLACE)
    db.execute(
        """INSERT INTO gsc_daily_stats
           (project_id, property_url, date, date_jalali, clicks, impressions, ctr, position, queries_json, pages_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(property_url, date) DO UPDATE SET
             clicks=excluded.clicks,
             impressions=excluded.impressions,
             ctr=excluded.ctr,
             position=excluded.position,
             queries_json=excluded.queries_json,
             pages_json=excluded.pages_json,
             project_id=excluded.project_id
        """,
        (
            project_id, property_url, date, date_jalali, clicks, impressions, ctr, position,
            json.dumps(queries or [], ensure_ascii=False),
            json.dumps(pages or [], ensure_ascii=False),
            t,
        ),
    )


def save_ga4_daily(
    *,
    project_id: int | None,
    property_id: str,
    date: str,
    sessions: int = 0,
    users: int = 0,
    pageviews: int = 0,
    conversions: int = 0,
    bounce_rate: float = 0,
    channels: list[dict] | None = None,
    pages: list[dict] | None = None,
) -> None:
    try:
        gy, gm, gd = map(int, date.split("-"))
        jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
        date_jalali = f"{jy:04d}-{jm:02d}-{jd:02d}"
    except Exception:
        date_jalali = ""

    t = db.now()
    db.execute(
        """INSERT INTO ga4_daily_stats
           (project_id, property_id, date, date_jalali, sessions, users, pageviews, conversions, bounce_rate, channels_json, pages_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(property_id, date) DO UPDATE SET
             sessions=excluded.sessions,
             users=excluded.users,
             pageviews=excluded.pageviews,
             conversions=excluded.conversions,
             bounce_rate=excluded.bounce_rate,
             channels_json=excluded.channels_json,
             pages_json=excluded.pages_json,
             project_id=excluded.project_id
        """,
        (
            project_id, property_id, date, date_jalali, sessions, users, pageviews, conversions, bounce_rate,
            json.dumps(channels or [], ensure_ascii=False),
            json.dumps(pages or [], ensure_ascii=False),
            t,
        ),
    )


def get_gsc_daily_trend(
    *,
    property_url: str | None = None,
    project_id: int | None = None,
    days: int = 28,
) -> dict:
    """Get daily trend for charts — from stored stats."""
    sql = "SELECT date, date_jalali, clicks, impressions, ctr, position FROM gsc_daily_stats WHERE 1=1"
    params: list[Any] = []
    if property_url:
        sql += " AND property_url=?"
        params.append(property_url)
    if project_id is not None:
        sql += " AND project_id=?"
        params.append(project_id)
    sql += " ORDER BY date DESC LIMIT ?"
    params.append(days)

    rows = db.query_all(sql, tuple(params))
    rows = list(reversed(rows))  # chronological

    return {
        "dates": [r["date"] for r in rows],
        "dates_jalali": [r["date_jalali"] for r in rows],
        "clicks": [r["clicks"] for r in rows],
        "impressions": [r["impressions"] for r in rows],
        "ctr": [r["ctr"] for r in rows],
        "position": [r["position"] for r in rows],
    }


def get_ga4_daily_trend(
    *,
    property_id: str | None = None,
    project_id: int | None = None,
    days: int = 28,
) -> dict:
    sql = "SELECT date, date_jalali, sessions, users, pageviews, conversions FROM ga4_daily_stats WHERE 1=1"
    params: list[Any] = []
    if property_id:
        sql += " AND property_id=?"
        params.append(property_id)
    if project_id is not None:
        sql += " AND project_id=?"
        params.append(project_id)
    sql += " ORDER BY date DESC LIMIT ?"
    params.append(days)

    rows = db.query_all(sql, tuple(params))
    rows = list(reversed(rows))

    return {
        "dates": [r["date"] for r in rows],
        "dates_jalali": [r["date_jalali"] for r in rows],
        "sessions": [r["sessions"] for r in rows],
        "users": [r["users"] for r in rows],
        "pageviews": [r["pageviews"] for r in rows],
        "conversions": [r["conversions"] for r in rows],
    }


def sync_gsc_to_storage(
    *,
    creds: dict,
    property_url: str,
    project_id: int | None,
    days: int = 28,
) -> int:
    """Fetch daily GSC data and store in gsc_daily_stats — returns count saved."""
    from app.integrations.google import gsc_query
    from datetime import datetime, timedelta, timezone

    # Fetch daily breakdown
    end_dt = datetime.now(timezone.utc) - timedelta(days=3)
    start_dt = end_dt - timedelta(days=days)

    try:
        data = gsc_query(
            creds,
            property_url,
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=end_dt.strftime("%Y-%m-%d"),
            dimensions=["date"],
            row_limit=1000,
        )
        rows = data.get("rows", [])
        count = 0
        for r in rows:
            keys = r.get("keys", [])
            if not keys:
                continue
            date_str = keys[0]
            save_gsc_daily(
                project_id=project_id,
                property_url=property_url,
                date=date_str,
                clicks=int(r.get("clicks", 0)),
                impressions=int(r.get("impressions", 0)),
                ctr=float(r.get("ctr", 0)),
                position=float(r.get("position", 0)),
            )
            count += 1
        return count
    except Exception as exc:
        from app.logging_config import get_logger
        log = get_logger("gsc_storage")
        log.warning("gsc.sync_failed", extra={"extra_fields": {"error": str(exc)}})
        return 0
