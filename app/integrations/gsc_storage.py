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
    start_s, end_s = start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")

    try:
        data = gsc_query(
            creds,
            property_url,
            start_date=start_s,
            end_date=end_s,
            dimensions=["date"],
            row_limit=1000,
        )
        rows = data.get("rows", [])

        # Per-date totals + top pages/queries. The page/query breakdown powers the
        # declining-pages and cannibalization detectors without extra API quota.
        by_date: dict[str, dict] = {}
        for r in rows:
            keys = r.get("keys", [])
            if not keys:
                continue
            by_date[keys[0]] = {
                "clicks": int(r.get("clicks", 0)),
                "impressions": int(r.get("impressions", 0)),
                "ctr": float(r.get("ctr", 0)),
                "position": float(r.get("position", 0)),
                "pages": [],
                "queries": [],
            }

        for dims, bucket, limit in ((["date", "page"], "pages", 15), (["date", "query"], "queries", 15)):
            try:
                detail = gsc_query(
                    creds,
                    property_url,
                    start_date=start_s,
                    end_date=end_s,
                    dimensions=dims,
                    row_limit=2500,
                )
                for r in detail.get("rows", []):
                    keys = r.get("keys", [])
                    if len(keys) < 2 or keys[0] not in by_date:
                        continue
                    item = {
                        dims[1]: keys[1],
                        "clicks": int(r.get("clicks", 0)),
                        "impressions": int(r.get("impressions", 0)),
                        "ctr": float(r.get("ctr", 0)),
                        "position": float(r.get("position", 0)),
                    }
                    by_date[keys[0]][bucket].append(item)
                # keep the strongest rows per date to keep JSON small
                for d in by_date.values():
                    d[bucket].sort(key=lambda x: x["impressions"], reverse=True)
                    d[bucket] = d[bucket][:limit]
            except Exception:  # noqa: BLE001 — breakdowns are best-effort
                pass

        count = 0
        for date_str, tot in by_date.items():
            save_gsc_daily(
                project_id=project_id,
                property_url=property_url,
                date=date_str,
                clicks=tot["clicks"],
                impressions=tot["impressions"],
                ctr=tot["ctr"],
                position=tot["position"],
                queries=tot["queries"],
                pages=tot["pages"],
            )
            count += 1
        return count
    except Exception as exc:
        from app.logging_config import get_logger
        log = get_logger("gsc_storage")
        log.warning("gsc.sync_failed", extra={"extra_fields": {"error": str(exc)}})
        return 0


def get_declining_pages(
    *,
    days: int = 28,
    min_impressions: int = 200,
    threshold: float = 0.3,
    limit: int = 8,
) -> list[dict]:
    """Pages whose clicks dropped >threshold vs the previous equal period.

    Pure storage read (no Google API) — powers the 'صفحات در حال مرگ' card:
    compare last `days` vs the `days` before it, from gsc_daily_stats.pages_json.
    """
    from datetime import date as _date, timedelta as _td

    today = _date.today()
    cur_start = (today - _td(days=days)).isoformat()
    prev_start = (today - _td(days=2 * days)).isoformat()

    prev_rows = db.query_all(
        "SELECT pages_json FROM gsc_daily_stats WHERE date >= ? AND date < ? AND pages_json != '[]'",
        (prev_start, cur_start),
    )
    cur_rows = db.query_all(
        "SELECT pages_json FROM gsc_daily_stats WHERE date >= ? AND pages_json != '[]'",
        (cur_start,),
    )

    def _agg(rs) -> dict[str, dict]:
        agg: dict[str, dict] = {}
        for r in rs:
            try:
                items = json.loads(r["pages_json"])
            except (ValueError, TypeError):
                continue
            for it in items:
                page = it.get("page")
                if not page:
                    continue
                slot = agg.setdefault(page, {"clicks": 0, "impressions": 0})
                slot["clicks"] += it.get("clicks", 0)
                slot["impressions"] += it.get("impressions", 0)
        return agg

    prev, cur = _agg(prev_rows), _agg(cur_rows)

    out: list[dict] = []
    for page, p in prev.items():
        if p["impressions"] < min_impressions or p["clicks"] <= 0:
            continue
        c = cur.get(page, {"clicks": 0, "impressions": 0})
        drop = (p["clicks"] - c["clicks"]) / p["clicks"]
        if drop >= threshold:
            out.append({
                "page": page,
                "prev_clicks": p["clicks"],
                "cur_clicks": c["clicks"],
                "prev_impressions": p["impressions"],
                "cur_impressions": c["impressions"],
                "drop_percent": round(drop * 100),
            })
    out.sort(key=lambda x: (-x["drop_percent"], -x["prev_clicks"]))
    return out[:limit]
