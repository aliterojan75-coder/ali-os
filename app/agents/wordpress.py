"""WordPress / WooCommerce agent (§3).

Talks to the WordPress REST API using the Application Password stored via the
integrations panel. Every write is exposed as an approval action, so a draft
is 🟡 (one tap) and an actual publish is 🔴 (two taps) — enforced centrally by
`app/approvals/risk.py`, not here.
"""
from __future__ import annotations

from typing import Any

import requests

from app.approvals.registry import executor
from app.integrations import store
from app.logging_config import get_logger

log = get_logger("agents.wordpress")

TIMEOUT = 30


class WordPressError(RuntimeError):
    pass


def _creds(project_id: int | None) -> tuple[str, tuple[str, str]]:
    creds = store.credentials("wordpress", project_id)
    site = (creds.get("site_url") or "").rstrip("/")
    user = creds.get("username") or ""
    password = creds.get("app_password") or ""
    if not (site and user and password):
        raise WordPressError(
            "اتصال وردپرس برای این پروژه تنظیم نشده است. از داشبورد → اتصال‌ها "
            "سایت را وصل کن."
        )
    return site, (user, password)


def _request(method: str, project_id: int | None, path: str, **kwargs) -> Any:
    site, auth = _creds(project_id)
    url = f"{site}/wp-json/wp/v2/{path.lstrip('/')}"
    try:
        resp = requests.request(method, url, auth=auth, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise WordPressError(f"ارتباط با سایت برقرار نشد: {type(exc).__name__}") from exc
    if resp.status_code == 401:
        raise WordPressError("احراز هویت وردپرس رد شد — Application Password را بررسی کن.")
    if resp.status_code == 403:
        raise WordPressError("این کاربر مجوز انجام این کار را ندارد.")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("message", "")
        except ValueError:
            detail = resp.text[:200]
        raise WordPressError(f"خطای وردپرس (HTTP {resp.status_code}): {detail}")
    try:
        return resp.json()
    except ValueError as exc:
        raise WordPressError("پاسخ سایت JSON معتبر نبود.") from exc


# ── Read helpers (no approval needed) ───────────────────────────────────────

def list_posts(project_id: int | None, *, status: str = "any",
               per_page: int = 10, search: str | None = None) -> list[dict]:
    params: dict[str, Any] = {"per_page": min(per_page, 50), "status": status}
    if search:
        params["search"] = search
    return _request("GET", project_id, "posts", params=params)


def list_categories(project_id: int | None) -> list[dict]:
    return _request("GET", project_id, "categories", params={"per_page": 100})


def content_index(project_id: int | None, limit: int = 100) -> list[dict]:
    """Titles + slugs of existing posts — the anti-cannibalisation check the
    گیاهکده rules require before proposing a new topic."""
    posts = _request("GET", project_id, "posts",
                     params={"per_page": min(limit, 100), "status": "publish",
                             "_fields": "id,title,slug,link,date"})
    return [
        {
            "id": p.get("id"),
            "title": (p.get("title") or {}).get("rendered", ""),
            "slug": p.get("slug"),
            "link": p.get("link"),
            "date": p.get("date"),
        }
        for p in posts
    ]


def _build_body(payload: dict) -> dict:
    body: dict[str, Any] = {}
    for key in ("title", "content", "excerpt", "slug", "status"):
        if payload.get(key) is not None:
            body[key] = payload[key]
    if payload.get("categories"):
        body["categories"] = payload["categories"]
    if payload.get("tags"):
        body["tags"] = payload["tags"]
    if payload.get("featured_media"):
        body["featured_media"] = payload["featured_media"]
    if payload.get("date"):           # scheduling
        body["date"] = payload["date"]
    # Rank Math SEO fields travel as post meta.
    meta = {}
    if payload.get("seo_title"):
        meta["rank_math_title"] = payload["seo_title"]
    if payload.get("seo_description"):
        meta["rank_math_description"] = payload["seo_description"]
    if payload.get("canonical"):
        meta["rank_math_canonical_url"] = payload["canonical"]
    if payload.get("focus_keyword"):
        meta["rank_math_focus_keyword"] = payload["focus_keyword"]
    if meta:
        body["meta"] = meta
    return body


# ── Approval-gated executors ────────────────────────────────────────────────

@executor("wordpress.create_draft")
def _create_draft(payload: dict, ctx: dict) -> str:
    project_id = payload.get("project_id") or ctx.get("project_id")
    if not payload.get("title"):
        raise ValueError("عنوان مقاله لازم است")
    body = _build_body({**payload, "status": payload.get("status", "draft")})
    post = _request("POST", project_id, "posts", json=body)
    return f"پیش‌نویس ساخته شد: {post.get('link') or post.get('id')}"


@executor("wordpress.update_post")
def _update_post(payload: dict, ctx: dict) -> str:
    project_id = payload.get("project_id") or ctx.get("project_id")
    post_id = payload.get("post_id")
    if not post_id:
        raise ValueError("post_id لازم است")
    body = _build_body(payload)
    if not body:
        raise ValueError("هیچ تغییری داده نشد")
    post = _request("POST", project_id, f"posts/{post_id}", json=body)
    return f"مقاله {post_id} به‌روزرسانی شد: {post.get('link') or ''}".strip()


@executor("wordpress.publish")
def _publish(payload: dict, ctx: dict) -> str:
    """🔴 two-step approval — this makes content publicly visible."""
    project_id = payload.get("project_id") or ctx.get("project_id")
    post_id = payload.get("post_id")
    if post_id:
        body = {"status": "publish"}
        if payload.get("date"):
            body = {"status": "future", "date": payload["date"]}
        post = _request("POST", project_id, f"posts/{post_id}", json=body)
    else:
        if not payload.get("title"):
            raise ValueError("برای انتشار مستقیم، عنوان لازم است")
        post = _request("POST", project_id, "posts",
                        json=_build_body({**payload, "status": "publish"}))
    return f"منتشر شد: {post.get('link') or post.get('id')}"


@executor("wordpress.delete_post")
def _delete_post(payload: dict, ctx: dict) -> str:
    """🔴 — moves the post to trash (not a permanent delete)."""
    project_id = payload.get("project_id") or ctx.get("project_id")
    post_id = payload.get("post_id")
    if not post_id:
        raise ValueError("post_id لازم است")
    _request("DELETE", project_id, f"posts/{post_id}", params={"force": "false"})
    return f"مقاله {post_id} به زباله‌دان منتقل شد"
