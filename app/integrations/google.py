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


def get_access_token(creds: dict) -> str:
    """Exchange refresh token for access token."""
    client_id = creds.get("client_id") or ""
    client_secret = creds.get("client_secret") or ""
    refresh_token = creds.get("refresh_token") or ""

    if not (client_id and client_secret and refresh_token):
        raise GoogleAuthError("اطلاعات OAuth ناقص است — client_id, client_secret, refresh_token لازم است")

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


# ── Combined dashboard data ──────────────────────────────────────────────────

def get_project_google_data(
    *,
    gsc_creds: dict | None,
    gsc_property: str | None,
    ga4_creds: dict | None,
    ga4_property: str | None,
) -> dict:
    """Fetch combined Google data for a project — for dossier / morning report."""
    result: dict[str, Any] = {
        "gsc": None,
        "ga4": None,
        "errors": [],
    }

    if gsc_creds and gsc_property:
        try:
            # Last 28 days, top queries and pages
            queries = gsc_top_queries(gsc_creds, gsc_property, limit=10)
            pages = gsc_top_pages(gsc_creds, gsc_property, limit=10)
            # Overall stats
            overall = gsc_query(gsc_creds, gsc_property, dimensions=[], row_limit=1)
            rows = overall.get("rows", [])
            totals = rows[0] if rows else {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}

            result["gsc"] = {
                "property": gsc_property,
                "totals": totals,
                "top_queries": queries,
                "top_pages": pages,
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
            # Parse totals
            totals = {}
            try:
                # GA4 returns metricHeaders and rows, plus totals
                # For simplicity, sum first rows
                totals_row = report.get("totals", [{}])[0] if report.get("totals") else {}
                if totals_row.get("metricValues"):
                    # Map to metrics
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
                "fetched_at": time.time(),
            }
        except Exception as exc:
            result["errors"].append(f"GA4: {exc}")
            log.warning("google.ga4_fetch_failed", extra={"extra_fields": {"error": str(exc)}})

    return result
