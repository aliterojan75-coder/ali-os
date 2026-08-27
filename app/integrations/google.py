"""Google integrations — Search Console and GA4 data fetching (§4, §5).

Handles OAuth2 refresh token exchange and API calls for:
- Search Console: searchanalytics.query
- GA4: Data API runReport

All functions are stateless and work with credentials stored via integrations panel.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from app.logging_config import get_logger

log = get_logger("integrations.google")

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"
GA4_API_BASE = "https://analyticsdata.googleapis.com/v1beta"

TIMEOUT = 30

# Scopes needed
SCOPES = {
    "google_search_console": ["https://www.googleapis.com/auth/webmasters.readonly"],
    "google_analytics": ["https://www.googleapis.com/auth/analytics.readonly"],
}


class GoogleAuthError(RuntimeError):
    pass


class GoogleAPIError(RuntimeError):
    pass


# ── Caches ───────────────────────────────────────────────────────────────────
# Google access tokens are valid ~60 min. Refreshing them on EVERY API call was
# one extra RTT per request (×10 calls per dashboard load) — cached here with a
# 5-min safety margin. TTLs are env-overridable for tests.
import os as _os
import threading as _threading
import hashlib as _hashlib

_TOKEN_CACHE: dict[str, tuple[float, str]] = {}
_TOKEN_TTL = int(_os.environ.get("GOOGLE_TOKEN_CACHE_TTL", 55 * 60))

# GSC data lags 2-3 days by nature; re-hitting Google on every panel open was
# pure latency. get_project_google_data() results are memoized per property.
_OVERVIEW_CACHE: dict[str, tuple[float, dict]] = {}
_OVERVIEW_TTL = int(_os.environ.get("GOOGLE_DATA_CACHE_TTL", 30 * 60))
_CACHE_LOCK = _threading.Lock()
_CACHE_MAX = 32


def _cache_put(store: dict, key: str, value, ttl: int) -> None:
    with _CACHE_LOCK:
        if len(store) >= _CACHE_MAX:  # simple eviction guard for the free tier
            store.pop(next(iter(store)), None)
        store[key] = (_time_now() + ttl, value)


def _time_now() -> float:
    import time as _t
    return _t.time()


def cache_clear() -> None:
    """Drop cached tokens + overviews (used after re-saving Google credentials, and by tests)."""
    with _CACHE_LOCK:
        _TOKEN_CACHE.clear()
        _OVERVIEW_CACHE.clear()


def get_access_token(creds: dict) -> str:
    """Exchange refresh token for access token (cached — see _TOKEN_CACHE)."""
    client_id = creds.get("client_id") or ""
    client_secret = creds.get("client_secret") or ""
    refresh_token = creds.get("refresh_token") or ""

    if not (client_id and client_secret and refresh_token):
        raise GoogleAuthError("اطلاعات OAuth ناقص است — client_id, client_secret, refresh_token لازم است")

    token_key = f"{client_id}:{_hashlib.sha256(refresh_token.encode()).hexdigest()[:16]}"
    with _CACHE_LOCK:
        hit = _TOKEN_CACHE.get(token_key)
    if hit and hit[0] > _time_now():
        return hit[1]

    try:
        resp = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GoogleAuthError(f"اتصال به گوگل برقرار نشد: {type(exc).__name__}") from exc

    if not resp.ok:
        try:
            data = resp.json()
            err = data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}"
        except ValueError:
            err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        raise GoogleAuthError(f"توکن گوگل نامعتبر است: {err}")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise GoogleAuthError("پاسخ گوگل access_token نداشت")
    _cache_put(_TOKEN_CACHE, token_key, access_token, _TOKEN_TTL)
    return access_token


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


# ── Search Console ───────────────────────────────────────────────────────────

def gsc_query(
    creds: dict,
    property_url: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    dimensions: list[str] | None = None,
    row_limit: int = 100,
    start_row: int = 0,
) -> dict:
    """Run Search Console searchanalytics.query.

    Dates: YYYY-MM-DD, defaults to last 28 days (GSC data has 2-3 days delay).
    Dimensions: query, page, country, device, searchAppearance
    Returns raw API response with rows.
    """
    if not property_url:
        raise GoogleAPIError("property_url لازم است")

    # Default dates: last 28 days ending 3 days ago (to account for GSC delay)
    if not end_date:
        end_dt = datetime.now(timezone.utc) - timedelta(days=3)
        end_date = end_dt.strftime("%Y-%m-%d")
    if not start_date:
        start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=28)
        start_date = start_dt.strftime("%Y-%m-%d")

    access_token = get_access_token(creds)

    url = f"{GSC_API_BASE}/sites/{requests.utils.quote(property_url, safe='')}/searchAnalytics/query"

    body: dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions if dimensions is not None else ["query"],
        "rowLimit": min(row_limit, 25000),
        "startRow": start_row,
    }

    try:
        resp = requests.post(url, headers=_auth_headers(access_token), json=body, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise GoogleAPIError(f"اتصال به Search Console برقرار نشد: {type(exc).__name__}") from exc

    if not resp.ok:
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message") or str(err)[:500]
        except ValueError:
            msg = f"HTTP {resp.status_code}: {resp.text[:500]}"
        raise GoogleAPIError(f"خطای Search Console: {msg}")

    return resp.json()


def gsc_list_sites(creds: dict) -> list[dict]:
    """List Search Console properties (sites) — useful for validation."""
    access_token = get_access_token(creds)
    url = f"{GSC_API_BASE}/sites"
    try:
        resp = requests.get(url, headers=_auth_headers(access_token), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise GoogleAPIError(f"اتصال به GSC برقرار نشد: {type(exc).__name__}") from exc

    if not resp.ok:
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message") or str(err)[:500]
        except ValueError:
            msg = f"HTTP {resp.status_code}"
        raise GoogleAPIError(f"خطای لیست سایت‌ها: {msg}")

    data = resp.json()
    return data.get("siteEntry", [])


def gsc_top_queries(
    creds: dict,
    property_url: str,
    *,
    limit: int = 20,
) -> list[dict]:
    """Get top queries by clicks."""
    try:
        data = gsc_query(creds, property_url, dimensions=["query"], row_limit=limit)
        rows = data.get("rows", [])
        # Sort by clicks desc
        rows.sort(key=lambda r: r.get("clicks", 0), reverse=True)
        return rows[:limit]
    except Exception as exc:
        log.warning("gsc.top_queries_failed", extra={"extra_fields": {"error": str(exc)}})
        return []


def gsc_top_pages(
    creds: dict,
    property_url: str,
    *,
    limit: int = 20,
) -> list[dict]:
    try:
        data = gsc_query(creds, property_url, dimensions=["page"], row_limit=limit)
        rows = data.get("rows", [])
        rows.sort(key=lambda r: r.get("clicks", 0), reverse=True)
        return rows[:limit]
    except Exception as exc:
        log.warning("gsc.top_pages_failed", extra={"extra_fields": {"error": str(exc)}})
        return []


# ── GA4 ──────────────────────────────────────────────────────────────────────

def ga4_run_report(
    creds: dict,
    property_id: str,
    *,
    metrics: list[str] | None = None,
    dimensions: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
) -> dict:
    """Run GA4 Data API report.

    property_id: numeric GA4 property ID (e.g., 123456789)
    metrics: e.g., ["sessions", "totalUsers", "conversions", "bounceRate"]
    dimensions: e.g., ["pagePath", "sessionDefaultChannelGroup", "country"]
    """
    if not property_id:
        raise GoogleAPIError("property_id لازم است")

    if not end_date:
        end_dt = datetime.now(timezone.utc)
        end_date = end_dt.strftime("%Y-%m-%d")
    if not start_date:
        start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=28)
        start_date = start_dt.strftime("%Y-%m-%d")

    access_token = get_access_token(creds)

    # GA4 property ID should be numeric, but API expects "properties/123"
    prop = property_id.strip()
    if not prop.startswith("properties/"):
        prop = f"properties/{prop}"

    url = f"{GA4_API_BASE}/{prop}:runReport"

    body: dict[str, Any] = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "metrics": [{"name": m} for m in (metrics or ["sessions", "totalUsers", "screenPageViews"])],
        "dimensions": [{"name": d} for d in (dimensions or ["pagePathPlusQueryString"])],
        "limit": min(limit, 100000),
    }

    try:
        resp = requests.post(url, headers=_auth_headers(access_token), json=body, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise GoogleAPIError(f"اتصال به GA4 برقرار نشد: {type(exc).__name__}") from exc

    if not resp.ok:
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message") or str(err)[:500]
        except ValueError:
            msg = f"HTTP {resp.status_code}: {resp.text[:500]}"
        raise GoogleAPIError(f"خطای GA4: {msg}")

    return resp.json()


def ga4_realtime_report(
    creds: dict,
    property_id: str,
) -> dict:
    """Get GA4 realtime report — active users right now."""
    if not property_id:
        raise GoogleAPIError("property_id لازم است")

    access_token = get_access_token(creds)
    prop = property_id.strip()
    if not prop.startswith("properties/"):
        prop = f"properties/{prop}"

    url = f"{GA4_API_BASE}/{prop}:runRealtimeReport"
    body = {
        "metrics": [{"name": "activeUsers"}],
        "dimensions": [{"name": "country"}, {"name": "pagePathPlusQueryString"}],
        "limit": 20,
    }

    try:
        resp = requests.post(url, headers=_auth_headers(access_token), json=body, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise GoogleAPIError(f"اتصال به GA4 realtime برقرار نشد: {type(exc).__name__}") from exc

    if not resp.ok:
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message") or str(err)[:500]
        except ValueError:
            msg = f"HTTP {resp.status_code}"
        raise GoogleAPIError(f"خطای GA4 realtime: {msg}")

    return resp.json()


def gsc_daily_trend(
    creds: dict,
    property_url: str,
    *,
    days: int = 28,
) -> dict:
    """Fetch daily clicks/impressions for chart — last N days."""
    from datetime import datetime, timedelta, timezone
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
        rows.sort(key=lambda r: r.get("keys", [""])[0])
        return {
            "dates": [r["keys"][0] for r in rows if r.get("keys")],
            "clicks": [int(r.get("clicks", 0)) for r in rows],
            "impressions": [int(r.get("impressions", 0)) for r in rows],
            "ctr": [float(r.get("ctr", 0)) for r in rows],
            "position": [float(r.get("position", 0)) for r in rows],
        }
    except Exception as exc:
        log.warning("gsc.daily_trend_failed", extra={"extra_fields": {"error": str(exc)}})
        return {"dates": [], "clicks": [], "impressions": [], "ctr": [], "position": []}


def gsc_cannibalization(
    creds: dict,
    property_url: str,
    *,
    days: int = 28,
    min_impressions: int = 50,
    limit: int = 10,
) -> list[dict]:
    """Queries that Google shows for TWO+ of your pages — real cannibalization.

    One GSC call with dimensions=["query","page"] grouped per query. This is the
    ground truth; the Jaccard-on-titles check is only a fallback for when GSC is
    not connected or the property is too young.
    """
    end_dt = datetime.now(timezone.utc) - timedelta(days=3)
    start_dt = end_dt - timedelta(days=days)
    data = gsc_query(
        creds,
        property_url,
        start_date=start_dt.strftime("%Y-%m-%d"),
        end_date=end_dt.strftime("%Y-%m-%d"),
        dimensions=["query", "page"],
        row_limit=2500,
    )

    by_query: dict[str, dict] = {}
    for r in data.get("rows", []):
        keys = r.get("keys", [])
        if len(keys) < 2:
            continue
        query, page = keys[0], keys[1]
        e = by_query.setdefault(query, {"query": query, "impressions": 0, "clicks": 0, "pages": {}})
        e["impressions"] += int(r.get("impressions", 0))
        e["clicks"] += int(r.get("clicks", 0))
        p = e["pages"].setdefault(page, {"page": page, "impressions": 0, "clicks": 0, "best_position": None})
        p["impressions"] += int(r.get("impressions", 0))
        p["clicks"] += int(r.get("clicks", 0))
        pos = float(r.get("position", 0) or 0)
        if pos and (p["best_position"] is None or pos < p["best_position"]):
            p["best_position"] = round(pos, 1)

    out: list[dict] = []
    for e in by_query.values():
        if len(e["pages"]) >= 2 and e["impressions"] >= min_impressions:
            pages = sorted(e["pages"].values(), key=lambda x: -x["impressions"])
            out.append({
                "query": e["query"],
                "impressions": e["impressions"],
                "clicks": e["clicks"],
                "pages": pages[:4],
                "suggestion": "ادغام محتوا یا کانالیزه کردن با canonical/internal link بین این صفحات",
            })
    out.sort(key=lambda x: -x["impressions"])
    return out[:limit]


def gsc_device_breakdown(
    creds: dict,
    property_url: str,
    *,
    days: int = 28,
) -> list[dict]:
    try:
        data = gsc_query(
            creds,
            property_url,
            dimensions=["device"],
            row_limit=10,
        )
        return data.get("rows", [])
    except Exception as exc:
        log.warning("gsc.device_failed", extra={"extra_fields": {"error": str(exc)}})
        return []


def gsc_country_breakdown(
    creds: dict,
    property_url: str,
    *,
    days: int = 28,
) -> list[dict]:
    try:
        data = gsc_query(
            creds,
            property_url,
            dimensions=["country"],
            row_limit=20,
        )
        return data.get("rows", [])
    except Exception as exc:
        log.warning("gsc.country_failed", extra={"extra_fields": {"error": str(exc)}})
        return []


def ga4_daily_trend(
    creds: dict,
    property_id: str,
    *,
    days: int = 28,
) -> dict:
    from datetime import datetime, timedelta, timezone
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    try:
        report = ga4_run_report(
            creds,
            property_id,
            metrics=["sessions", "totalUsers", "screenPageViews"],
            dimensions=["date"],
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=end_dt.strftime("%Y-%m-%d"),
            limit=1000,
        )
        rows = report.get("rows", [])
        # GA4 date format is YYYYMMDD, convert to YYYY-MM-DD
        dates = []
        sessions = []
        users = []
        pageviews = []
        for r in rows:
            dim_vals = r.get("dimensionValues", [])
            met_vals = r.get("metricValues", [])
            if not dim_vals or not met_vals:
                continue
            date_raw = dim_vals[0].get("value", "")
            # Convert YYYYMMDD to YYYY-MM-DD
            if len(date_raw) == 8:
                date_fmt = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
            else:
                date_fmt = date_raw
            dates.append(date_fmt)
            # metrics order: sessions, totalUsers, screenPageViews
            try:
                sessions.append(int(met_vals[0].get("value", "0")))
                users.append(int(met_vals[1].get("value", "0")) if len(met_vals) > 1 else 0)
                pageviews.append(int(met_vals[2].get("value", "0")) if len(met_vals) > 2 else 0)
            except Exception:
                pass

        return {"dates": dates, "sessions": sessions, "users": users, "pageviews": pageviews}
    except Exception as exc:
        log.warning("ga4.daily_trend_failed", extra={"extra_fields": {"error": str(exc)}})
        return {"dates": [], "sessions": [], "users": [], "pageviews": []}


# ── Combined dashboard data ──────────────────────────────────────────────────

def get_project_google_data(
    *,
    gsc_creds: dict | None,
    gsc_property: str | None,
    ga4_creds: dict | None,
    ga4_property: str | None,
    force_refresh: bool = False,
) -> dict:
    """Fetch combined Google data for a project — for dossier / morning report.

    Memoized per property pair (default 30 min): GSC data lags 2-3 days anyway,
    and hitting ~10 Google endpoints synchronously on a 1-worker free host made
    the dashboard crawl. Use `fresh=1` (or force_refresh) on the manual sync button.
    """
    cache_key = f"{gsc_property or ''}|{ga4_property or ''}"
    if not force_refresh:
        with _CACHE_LOCK:
            hit = _OVERVIEW_CACHE.get(cache_key)
        if hit and hit[0] > _time_now():
            out = dict(hit[1])
            out["cached"] = True
            return out

    result: dict[str, Any] = {
        "gsc": None,
        "ga4": None,
        "errors": [],
    }

    if gsc_creds and gsc_property:
        try:
            # Last 28 days, top queries and pages + daily trend + device breakdown
            queries = gsc_top_queries(gsc_creds, gsc_property, limit=10)
            pages = gsc_top_pages(gsc_creds, gsc_property, limit=10)
            daily = gsc_daily_trend(gsc_creds, gsc_property, days=28)
            devices = gsc_device_breakdown(gsc_creds, gsc_property, days=28)
            countries = gsc_country_breakdown(gsc_creds, gsc_property, days=28)
            # Overall stats
            overall = gsc_query(gsc_creds, gsc_property, dimensions=[], row_limit=1)
            rows = overall.get("rows", [])
            totals = rows[0] if rows else {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}

            result["gsc"] = {
                "property": gsc_property,
                "totals": totals,
                "top_queries": queries,
                "top_pages": pages,
                "daily": daily,
                "devices": devices,
                "countries": countries,
                "fetched_at": time.time(),
            }
        except Exception as exc:
            result["errors"].append(f"GSC: {exc}")
            log.warning("google.gsc_fetch_failed", extra={"extra_fields": {"error": str(exc)}})

    if ga4_creds and ga4_property:
        try:
            report = ga4_run_report(
                ga4_creds,
                ga4_property,
                metrics=["sessions", "totalUsers", "screenPageViews", "conversions", "bounceRate"],
                dimensions=["sessionDefaultChannelGroup"],
                limit=10,
            )
            daily = ga4_daily_trend(ga4_creds, ga4_property, days=28)
            # Parse totals
            totals = {}
            try:
                totals_row = report.get("totals", [{}])[0] if report.get("totals") else {}
                if totals_row.get("metricValues"):
                    metrics_list = ["sessions", "totalUsers", "screenPageViews", "conversions", "bounceRate"]
                    for i, mv in enumerate(totals_row["metricValues"]):
                        if i < len(metrics_list):
                            totals[metrics_list[i]] = mv.get("value")
            except Exception:
                pass

            result["ga4"] = {
                "property": ga4_property,
                "totals": totals,
                "rows": report.get("rows", [])[:10],
                "daily": daily,
                "fetched_at": time.time(),
            }
        except Exception as exc:
            result["errors"].append(f"GA4: {exc}")
            log.warning("google.ga4_fetch_failed", extra={"extra_fields": {"error": str(exc)}})

    # Cache only when at least one source succeeded — never poison the cache with total failures.
    if result["gsc"] or result["ga4"]:
        _cache_put(_OVERVIEW_CACHE, cache_key, result, _OVERVIEW_TTL)
    return result
