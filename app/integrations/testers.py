"""Live connection tests.

Saving credentials is not the same as them working. Each tester performs one
cheap, read-only call and returns a short Persian verdict, so Ali finds out
immediately — not when an agent fails mid-task hours later.

Every tester returns (ok, message, details) and must never raise.
"""
from __future__ import annotations

from typing import Any

import requests

from app.logging_config import get_logger

log = get_logger("integrations.testers")

TIMEOUT = 20


def _wordpress(creds: dict) -> tuple[bool, str, dict]:
    site = (creds.get("site_url") or "").rstrip("/")
    user = creds.get("username") or ""
    password = creds.get("app_password") or ""
    if not (site and user and password):
        return False, "اطلاعات ناقص است.", {}

    # /users/me needs authentication, so it validates the credentials too.
    url = f"{site}/wp-json/wp/v2/users/me"
    try:
        resp = requests.get(
            url, auth=(user, password), timeout=TIMEOUT,
            headers={"Accept": "application/json"},
        )
    except requests.RequestException as exc:
        return False, f"اتصال به سایت برقرار نشد: {type(exc).__name__}", {}

    if resp.status_code == 401:
        return False, ("نام کاربری یا Application Password اشتباه است. "
                       "دقت کن رمز اصلی حساب کار نمی‌کند."), {}
    if resp.status_code == 403:
        return False, "دسترسی رد شد — کاربر مجوز کافی ندارد.", {}
    if resp.status_code == 404:
        return False, ("REST API وردپرس پیدا نشد. آدرس سایت را بررسی کن یا "
                       "مطمئن شو افزونه‌ای REST API را غیرفعال نکرده باشد."), {}
    if resp.status_code >= 400:
        return False, f"پاسخ غیرمنتظره از سایت: HTTP {resp.status_code}", {}

    try:
        data = resp.json()
    except ValueError:
        return False, ("پاسخ سایت JSON معتبر نبود — احتمالاً آدرس به یک صفحه‌ی "
                       "HTML اشاره می‌کند."), {}

    name = data.get("name") or data.get("slug") or user
    roles = data.get("roles") or []
    details: dict[str, Any] = {"user": name, "roles": roles}

    # Is WooCommerce present? Useful context, never a failure.
    try:
        wc = requests.get(f"{site}/wp-json/", timeout=TIMEOUT)
        if wc.ok:
            namespaces = wc.json().get("namespaces", [])
            details["woocommerce"] = any(
                str(ns).startswith("wc/") for ns in namespaces
            )
    except Exception:  # noqa: BLE001 — optional probe
        pass

    can_publish = (not roles) or any(
        r in ("administrator", "editor", "author") for r in roles
    )
    suffix = "" if can_publish else " ⚠️ این کاربر اجازه‌ی انتشار مقاله ندارد."
    woo = " • WooCommerce فعال است" if details.get("woocommerce") else ""
    return True, f"متصل شد ✓ کاربر: {name}{woo}{suffix}", details


def _telegram_channel(creds: dict) -> tuple[bool, str, dict]:
    channel = (creds.get("channel_id") or "").strip()
    if not channel:
        return False, "شناسه کانال وارد نشده است.", {}
    from app.telegram.client import TelegramError, _call

    try:
        chat = _call("getChat", {"chat_id": channel})
    except TelegramError as exc:
        return False, (f"دسترسی به کانال ممکن نشد: {exc}. مطمئن شو بات در کانال "
                       "ادمین است."), {}
    title = chat.get("title") or channel
    return True, f"متصل شد ✓ کانال: {title}", {"title": title,
                                                "type": chat.get("type")}


def _smtp(creds: dict) -> tuple[bool, str, dict]:
    import smtplib

    host = creds.get("host") or ""
    port = int(creds.get("port") or 587)
    user = creds.get("username") or ""
    password = creds.get("password") or ""
    if not (host and user and password):
        return False, "اطلاعات ناقص است.", {}
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
            server.starttls()
        try:
            server.login(user, password)
        finally:
            server.quit()
    except Exception as exc:  # noqa: BLE001 — many smtplib error types
        return False, f"ورود به SMTP ناموفق بود: {type(exc).__name__}", {}
    return True, f"متصل شد ✓ {host}:{port}", {}


def _google_oauth(creds: dict, scope_hint: str) -> tuple[bool, str, dict]:
    """Exchange the refresh token for an access token — proves the grant works."""
    client_id = creds.get("client_id") or ""
    client_secret = creds.get("client_secret") or ""
    refresh_token = creds.get("refresh_token") or ""
    if not (client_id and client_secret and refresh_token):
        return False, "اطلاعات OAuth ناقص است.", {}
    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id, "client_secret": client_secret,
                "refresh_token": refresh_token, "grant_type": "refresh_token",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"اتصال به گوگل برقرار نشد: {type(exc).__name__}", {}
    if not resp.ok:
        try:
            err = resp.json().get("error_description") or resp.json().get("error")
        except ValueError:
            err = f"HTTP {resp.status_code}"
        return False, f"توکن گوگل معتبر نیست: {err}", {}
    return True, f"توکن گوگل معتبر است ✓ ({scope_hint})", {}


def _gsc(creds: dict) -> tuple[bool, str, dict]:
    # First check token validity
    ok, msg, details = _google_oauth(creds, "Search Console")
    if not ok:
        return ok, msg, details

    # Try to list sites to give more context
    try:
        from app.integrations.google import gsc_list_sites
        sites = gsc_list_sites(creds)
        property_url = creds.get("property_url") or ""
        if property_url:
            found = any(s.get("siteUrl") == property_url for s in sites)
            if found:
                return True, f"متصل شد ✓ Property یافت شد: {property_url} ({len(sites)} کل)", {"sites": len(sites), "property_found": True}
            else:
                return True, f"توکن معتبر است ✓ ولی Property {property_url} در لیست {len(sites)} سایت یافت نشد — آدرس را بررسی کن", {"sites": len(sites), "property_found": False}
        else:
            return True, f"توکن معتبر است ✓ {len(sites)} Property در Search Console", {"sites": len(sites)}
    except Exception as exc:
        # Token valid but listing failed — still ok, maybe insufficient scope
        return True, f"توکن معتبر است ✓ ولی لیست سایت‌ها خطا داد: {type(exc).__name__} — {exc}", {}


def _ga4(creds: dict) -> tuple[bool, str, dict]:
    ok, msg, details = _google_oauth(creds, "GA4")
    if not ok:
        return ok, msg, details

    # Try realtime report as a cheap check if property_id is given
    property_id = creds.get("property_id") or ""
    if property_id:
        try:
            from app.integrations.google import ga4_realtime_report
            rt = ga4_realtime_report(creds, property_id)
            active = 0
            try:
                # Parse activeUsers
                active = rt.get("totals", [{}])[0].get("metricValues", [{}])[0].get("value", "0")
            except Exception:
                pass
            return True, f"متصل شد ✓ GA4 Property {property_id} — کاربران فعال: {active}", {"property_id": property_id}
        except Exception as exc:
            return True, f"توکن معتبر است ✓ ولی GA4 Property {property_id} خطا داد: {exc}", {"property_id": property_id}
    else:
        return True, "توکن معتبر است ✓ ولی Property ID وارد نشده", {}


TESTERS = {
    "wordpress": _wordpress,
    "telegram_channel": _telegram_channel,
    "smtp": _smtp,
    "google_search_console": _gsc,
    "google_analytics": _ga4,
}


def test(service: str, creds: dict) -> tuple[bool, str, dict]:
    fn = TESTERS.get(service)
    if fn is None:
        return True, "برای این سرویس تست خودکار وجود ندارد؛ اطلاعات ذخیره شد.", {}
    try:
        return fn(creds)
    except Exception as exc:  # noqa: BLE001 — a tester must never break the API
        log.exception("integration.test_crashed",
                      extra={"extra_fields": {"service": service}})
        return False, f"تست با خطای غیرمنتظره متوقف شد: {type(exc).__name__}", {}
