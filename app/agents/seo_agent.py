"""SEO Agent (§8) — basic on-page SEO analysis.

- Checks meta title/description length, focus keyword presence, content length, cannibalization risk
- No external API needed for MVP; future Phase 3 will integrate GSC/GA4 data
"""

from __future__ import annotations

import json
import re
from typing import Any

from app import db
from app.content.repository import get_draft
from app.logging_config import get_logger

log = get_logger("seo_agent")


def _count_words(text: str) -> int:
    return len((text or "").split())


def _keyword_density(content: str, keyword: str) -> float:
    if not content or not keyword:
        return 0.0
    content_lower = content.lower()
    kw_lower = keyword.lower()
    count = content_lower.count(kw_lower)
    words = _count_words(content)
    return (count / words * 100) if words else 0.0


def audit_content(draft_uid: str, *, project_id: int | None = None) -> dict:
    """Run SEO audit on a content draft."""
    draft = get_draft(draft_uid)
    if not draft:
        raise ValueError(f"Draft not found: {draft_uid}")

    title = draft["title"] or ""
    content = draft["content"] or ""
    meta_title = draft["meta_title"] or ""
    meta_desc = draft["meta_description"] or ""
    focus_kw = draft["focus_keyword"] or ""
    excerpt = draft["excerpt"] or ""

    issues: list[str] = []
    suggestions: list[str] = []
    score = 100

    # Content length
    wc = _count_words(content)
    if wc < 300:
        issues.append(f"محتوا خیلی کوتاه است ({wc} کلمه)")
        score -= 30
        suggestions.append("حداقل ۱۵۰۰ کلمه برای مقاله جامع (گیاهکده: ۲۰۰۰ کلمه)")
    elif wc < 1000:
        issues.append(f"محتوا نسبتاً کوتاه است ({wc} کلمه)")
        score -= 15
        suggestions.append("تلاش کن به ۲۰۰۰ کلمه برسانی")
    elif wc >= 2000:
        suggestions.append("طول محتوا عالی است ✅")

    # Meta title
    has_meta_title = bool(meta_title)
    if not has_meta_title:
        issues.append("عنوان سئو (meta title) ندارد")
        score -= 10
    else:
        if len(meta_title) < 30:
            issues.append(f"عنوان سئو کوتاه است ({len(meta_title)} کاراکتر)")
            score -= 5
        elif len(meta_title) > 70:
            issues.append(f"عنوان سئو طولانی است ({len(meta_title)} کاراکتر)")
            score -= 5
        else:
            suggestions.append("طول عنوان سئو مناسب است ✅")

    # Meta description
    has_meta_desc = bool(meta_desc)
    if not has_meta_desc:
        issues.append("توضیحات متا ندارد")
        score -= 10
    else:
        if len(meta_desc) < 100:
            issues.append(f"توضیحات متا کوتاه است ({len(meta_desc)} کاراکتر)")
            score -= 5
        elif len(meta_desc) > 170:
            issues.append(f"توضیحات متا طولانی است ({len(meta_desc)} کاراکتر)")
            score -= 5
        else:
            suggestions.append("طول توضیحات متا مناسب است ✅")

    # Focus keyword
    has_focus = bool(focus_kw)
    if not has_focus:
        issues.append("کلمه کلیدی اصلی مشخص نشده")
        score -= 10
    else:
        # Check presence in title, meta, content, first paragraph
        if focus_kw.lower() not in title.lower():
            issues.append("کلمه کلیدی در عنوان نیست")
            score -= 5
        if focus_kw.lower() not in (meta_title + meta_desc).lower():
            issues.append("کلمه کلیدی در متا نیست")
            score -= 5
        density = _keyword_density(content, focus_kw)
        if density < 0.3:
            issues.append(f"تراکم کلمه کلیدی کم است ({density:.1f}٪)")
            score -= 5
        elif density > 3.0:
            issues.append(f"تراکم کلمه کلیدی زیاد است ({density:.1f}٪) — خطر keyword stuffing")
            score -= 10
        else:
            suggestions.append(f"تراکم کلمه کلیدی مناسب ({density:.1f}٪) ✅")

    # Cannibalization
    cannibal_risk = 0
    try:
        cannibal_json = draft["cannibalization_json"] or "[]"
        cannibal = json.loads(cannibal_json)
        if cannibal:
            cannibal_risk = max(c.get("similarity", 0) for c in cannibal)
            if cannibal_risk > 0.6:
                issues.append(f"ریسک بالای cannibalization (شباهت {cannibal_risk:.0%})")
                score -= 20
                suggestions.append("عنوان یا زاویه مقاله را تغییر بده تا با مقالات موجود هم‌پوشانی نداشته باشد")
            elif cannibal_risk > 0.4:
                issues.append(f"ریسک متوسط cannibalization ({cannibal_risk:.0%})")
                score -= 10
    except Exception:
        pass

    # FAQ, image_prompt, CTA
    try:
        faq = json.loads(draft["faq_json"] or "[]")
        if not faq:
            issues.append("FAQ ندارد")
            score -= 5
    except Exception:
        pass

    if not draft["image_prompt"]:
        issues.append("Image Prompt ندارد")
        score -= 3

    if not draft["cta"]:
        issues.append("CTA ندارد")
        score -= 3

    score = max(0, min(100, score))

    # Store audit
    audit_uid = db.new_uid("seo")
    t = db.now()
    db.execute(
        """INSERT INTO seo_audits
           (audit_uid, project_id, post_id, title, focus_keyword, score, issues_json, suggestions_json,
            content_length, has_meta_title, has_meta_desc, has_canonical, has_focus_keyword, cannibalization_risk, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            audit_uid,
            draft["project_id"],
            draft["wordpress_post_id"],
            title,
            focus_kw,
            score,
            json.dumps(issues, ensure_ascii=False),
            json.dumps(suggestions, ensure_ascii=False),
            wc,
            1 if has_meta_title else 0,
            1 if has_meta_desc else 0,
            1 if draft["canonical_url"] else 0,
            1 if has_focus else 0,
            int(cannibal_risk * 100),
            t,
        ),
    )

    # Update draft seo_score
    from app.content.repository import update_draft
    update_draft(draft_uid, seo_score=score, seo_notes=" | ".join(issues[:3]) if issues else "سئو مناسب")

    return {
        "audit_uid": audit_uid,
        "draft_uid": draft_uid,
        "score": score,
        "issues": issues,
        "suggestions": suggestions,
        "word_count": wc,
        "has_meta_title": has_meta_title,
        "has_meta_desc": has_meta_desc,
        "has_focus_keyword": has_focus,
        "cannibalization_risk": cannibal_risk,
    }


def quick_seo_check(
    *,
    title: str,
    content: str,
    meta_title: str | None = None,
    meta_description: str | None = None,
    focus_keyword: str | None = None,
) -> dict:
    """Lightweight check without DB — useful for API validation."""
    issues = []
    score = 100

    wc = _count_words(content)
    if wc < 300:
        issues.append("محتوا خیلی کوتاه")
        score -= 30
    if meta_title and len(meta_title) > 70:
        issues.append("عنوان سئو طولانی")
        score -= 5
    if meta_description and len(meta_description) > 170:
        issues.append("توضیحات متا طولانی")
        score -= 5
    if focus_keyword and focus_keyword.lower() not in title.lower():
        issues.append("کلمه کلیدی در عنوان نیست")
        score -= 5

    return {"score": max(0, score), "issues": issues, "word_count": wc}
