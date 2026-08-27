"""Content Agent (§9) — سنگ تموم: تولید محتوا حرفه‌ای با سئو و جلوگیری از Cannibalization.

قابلیت‌های کامل:
- بررسی cannibalization (گیاهکده rule) روی content_drafts + WordPress content_index
- پیشنهاد موضوع از GSC (ایمپرشن بالا، CTR پایین، جایگاه ۵-۲۰)
- تولید بریف محتوا (brief) قبل از تولید کامل
- تولید مقاله کامل با LLM: عنوان فارسی، slug انگلیسی، outline، محتوای ۲۰۰۰ کلمه‌ای B2B-aware، چکیده، FAQ، image_prompt، CTA، meta_title/description، focus_keyword
- بازنویسی و بهینه‌سازی سئو برای drafts موجود
- تقویم محتوا (content_calendar) — زمان‌بندی انتشار
- ردیابی عملکرد محتوا (اگر GSC متصل باشد، کلیک/نمایش برای هر مقاله)
- قالب‌های پروژه (گیاهکده، CropExport، esqom و...)
- تولید انواع محتوا: article, landing, product, FAQ page
"""

from __future__ import annotations

import json
import time
from typing import Any

from app import db, repositories as repo
from app.content.repository import create_draft, update_draft, get_draft, list_drafts
from app.llm import LLMMessage, get_provider
from app.logging_config import get_logger
from app.utils.jalali import fa_num

log = get_logger("content_agent")

# ── System Prompts ───────────────────────────────────────────────────────────

CONTENT_SYSTEM = """تو یک متخصص تولید محتوا و سئو برای پروژه‌های Ali OS هستی — بهترین نویسنده فارسی که هم B2B می‌فهمی هم سئو.

قوانین قطعی:
- محتوا باید فارسی روان، نتیجه‌محور و قابل اجرا باشد (نه تئوری کلی)
- برای پروژه گیاهکده: 
  * تمرکز B2B + مصرف‌کننده (خریدار عمده + خانگی)
  * از Cannibalization جلوگیری کن — قبل از موضوع جدید Content Index بررسی شود
  * مقالات جامع ~۲۰۰۰ کلمه با هدینگ‌های H2/H3
  * حتماً FAQ (۳-۵ سوال)، Image Prompt انگلیسی دقیق، CTA خرید عمده
  * English slug، متا تایتل/دسکریپشن با کلمه کلیدی
  * لحن: حرفه‌ای، صمیمی، متخصص گیاهان دارویی
- برای CropExport:
  * چندزبانه بودن را در نظر بگیر (فارسی پایه ولی هر زبان SEO مستقل)
  * MOQ، بسته‌بندی، ارقام محصول، فصل برداشت
  * B2B export focus
- برای esqom (امداد سرویس قم):
  * تمرکز SEO Recovery، محلی (قم)، اعتمادسازی، خدمات سریع
  * کلمات: تعمیر یخچال/لباسشویی/... در قم
- خروجی را فقط به صورت JSON معتبر برگردان — هیچ متن اضافی بیرون JSON ننویس

فیلدهای JSON مورد انتظار:
{
  "title": "عنوان جذاب فارسی (حداکثر ۷۰ کاراکتر)",
  "slug_en": "english-slug-for-url",
  "outline": ["مقدمه", "بخش ۱", "بخش ۲", "..."],
  "content": "متن کامل مقاله با هدینگ‌های H2/H3 به صورت Markdown — حداقل ۱۵۰۰ کلمه، جامع و کاربردی",
  "excerpt": "چکیده کوتاه ۱۵۰-۲۰۰ کاراکتر",
  "faq": [{"q": "سوال ۱؟", "a": "پاسخ کوتاه"}, ... ۳-۵ مورد],
  "image_prompt": "پرامپت انگلیسی برای تولید تصویر شاخص — دقیق و توصیفی",
  "cta": "دعوت به اقدام (مثلاً: برای خرید عمده تماس بگیرید)",
  "meta_title": "عنوان سئو ۵۰-۶۰ کاراکتر",
  "meta_description": "توضیحات متا ۱۴۰-۱۶۰ کاراکتر",
  "focus_keyword": "کلمه کلیدی اصلی فارسی",
  "canonical_url": null,
  "word_count": 1800,
  "tags": ["تگ۱", "تگ۲"],
  "content_type": "article"
}

اگر اطلاعات کافی نداری، با همین ساختار ولی با محتوای حداقلی برگردان — هرگز JSON نامعتبر نده.
"""

BRIEF_SYSTEM = """تو یک استراتژیست محتوا هستی. برای یک موضوع، یک بریف کامل تولید کن.

خروجی JSON:
{
  "topic": "موضوع اصلی",
  "target_audience": "مخاطب هدف (B2B, B2C, ...)",
  "search_intent": "اطلاعاتی، تراکنشی، ...",
  "primary_keyword": "کلمه کلیدی اصلی",
  "secondary_keywords": ["کلمه ۲", "کلمه ۳"],
  "outline": ["مقدمه", "بخش ۱", ...],
  "questions_to_answer": ["سوال ۱", "سوال ۲"],
  "cta_suggestion": "پیشنهاد CTA",
  "internal_links": ["عنوان مقاله مرتبط ۱", ...],
  "notes": "نکات خاص پروژه"
}
"""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    """Jaccard similarity on word sets."""
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def check_cannibalization(project_id: int | None, new_title: str, existing_limit: int = 100) -> list[dict]:
    """Check new title against existing content_index."""
    candidates: list[dict] = []

    # Check content_drafts
    try:
        if project_id is None:
            rows = db.query_all("SELECT title, slug_en FROM content_drafts ORDER BY updated_at DESC LIMIT ?", (existing_limit,))
        else:
            rows = db.query_all("SELECT title, slug_en FROM content_drafts WHERE project_id=? ORDER BY updated_at DESC LIMIT ?", (project_id, existing_limit))
        for r in rows:
            sim = _similarity(new_title, r["title"] or "")
            if sim > 0.3:
                candidates.append({"title": r["title"], "slug": r["slug_en"], "similarity": round(sim, 2), "source": "draft"})
    except Exception:
        pass

    # Check WordPress content_index
    try:
        from app.agents.wordpress import content_index
        wp_posts = content_index(project_id, limit=existing_limit)
        for p in wp_posts:
            sim = _similarity(new_title, p.get("title") or "")
            if sim > 0.35:
                candidates.append({"title": p.get("title"), "slug": p.get("slug"), "similarity": round(sim, 2), "source": "wordpress", "link": p.get("link")})
    except Exception:
        pass

    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates[:10]


def suggest_topics_from_gsc(
    *,
    project_id: int | None = None,
    creds: dict | None = None,
    property_url: str | None = None,
    limit: int = 15,
) -> list[dict]:
    """Suggest content topics from GSC data — high impressions, low CTR, position 5-20.

    If creds not provided, tries to find from integrations store.
    Returns list of suggested topics with reason.
    """
    # Find creds if not provided
    if not creds or not property_url:
        try:
            from app.integrations import store
            for pid in ([project_id] if project_id else []) + [None]:
                try:
                    row = store.find("google_search_console", pid)
                    if row:
                        creds = store.credentials("google_search_console", pid)
                        property_url = creds.get("property_url")
                        if not project_id:
                            project_id = pid
                        break
                except Exception:
                    pass
        except Exception:
            pass

    if not creds or not property_url:
        # No GSC data — fallback to project metadata existing_articles
        suggestions = []
        if project_id:
            proj = repo.get_project(project_id)
            if proj:
                try:
                    meta = json.loads(proj["metadata_json"] or "{}")
                    existing = meta.get("existing_articles", [])
                    products = meta.get("products", [])
                    # Suggest based on products not yet covered
                    for prod in products[:10]:
                        if not any(prod in art for art in existing):
                            suggestions.append({
                                "topic": f"فواید {prod} و کاربردهای آن",
                                "keyword": prod,
                                "reason": "محصول موجود ولی مقاله ندارد",
                                "source": "product_gap",
                                "impressions": 0,
                                "ctr": 0,
                                "position": 0,
                            })
                except Exception:
                    pass
        return suggestions[:limit]

    try:
        from app.integrations.google import gsc_query

        # Get queries with high impressions, low CTR, position 5-20
        data = gsc_query(
            creds,
            property_url,
            dimensions=["query"],
            row_limit=100,
        )
        rows = data.get("rows", [])

        opportunities = []
        for r in rows:
            keys = r.get("keys", [])
            if not keys:
                continue
            query = keys[0]
            clicks = r.get("clicks", 0)
            impressions = r.get("impressions", 0)
            ctr = r.get("ctr", 0)
            position = r.get("position", 0)

            # Opportunity criteria:
            # - impressions > 100
            # - CTR < 5% (low CTR = title/meta needs improvement or new content)
            # - position 5-20 (on page 1-2 but not top 3 — can improve)
            # - or position > 20 with high impressions (new content opportunity)
            if impressions > 100:
                if (ctr < 0.05 and 5 <= position <= 20) or (position > 20 and impressions > 500):
                    opportunities.append({
                        "topic": query,
                        "keyword": query,
                        "reason": f"ایمپرشن بالا ({impressions:.0f}) ولی CTR پایین ({ctr:.1%}) — جایگاه {position:.1f}",
                        "source": "gsc_opportunity",
                        "impressions": impressions,
                        "clicks": clicks,
                        "ctr": ctr,
                        "position": position,
                    })
                elif ctr < 0.03 and impressions > 200:
                    opportunities.append({
                        "topic": query,
                        "keyword": query,
                        "reason": f"CTR خیلی پایین ({ctr:.1%}) با {impressions:.0f} نمایش",
                        "source": "gsc_low_ctr",
                        "impressions": impressions,
                        "clicks": clicks,
                        "ctr": ctr,
                        "position": position,
                    })

        # Sort by impressions desc (biggest opportunity first)
        opportunities.sort(key=lambda x: x["impressions"], reverse=True)

        # Also check for queries with high clicks but no dedicated page (content gap)
        # For simplicity, we already have top queries — suggest articles for them

        return opportunities[:limit]

    except Exception as exc:
        log.warning("content.suggest_gsc_failed", extra={"extra_fields": {"error": str(exc)}})
        return []


def generate_brief(
    *,
    topic: str,
    project_id: int | None = None,
) -> dict:
    """Generate content brief via LLM."""
    project = repo.get_project(project_id) if project_id else None
    project_block = ""
    if project:
        try:
            meta = json.loads(project["metadata_json"] or "{}")
        except Exception:
            meta = {}
        project_block = f"""
پروژه: {project['name']} (slug={project['slug']})
صنعت: {project['industry'] or '—'}
یادداشت‌ها: {project['notes'] or '—'}
متادیتا: {json.dumps(meta, ensure_ascii=False, indent=2)}
"""

    cannibal = check_cannibalization(project_id, topic)
    cannibal_block = "مقالات مشابه:\n" + "\n".join(f"- {c['title']} ({c['similarity']})" for c in cannibal[:3]) if cannibal else "بدون مشابه"

    user_prompt = f"""{project_block}

موضوع: {topic}

{cannibal_block}

بریف کامل محتوا تولید کن.
"""

    llm = get_provider()
    messages = [
        LLMMessage(role="system", content=BRIEF_SYSTEM),
        LLMMessage(role="user", content=user_prompt),
    ]
    try:
        result = llm.structured_output(messages, temperature=0.4, max_tokens=1000)
        return result
    except Exception as exc:
        log.warning("content.brief_failed", extra={"extra_fields": {"error": str(exc)}})
        return {
            "topic": topic,
            "target_audience": "B2B + B2C",
            "search_intent": "اطلاعاتی",
            "primary_keyword": topic,
            "secondary_keywords": [],
            "outline": ["مقدمه", "بدنه", "نتیجه‌گیری"],
            "questions_to_answer": [f"{topic} چیست؟"],
            "cta_suggestion": "تماس بگیرید",
            "internal_links": [],
            "notes": "",
        }


def generate_article(
    *,
    topic: str,
    project_id: int | None = None,
    created_by: int | None = None,
    target_words: int = 2000,
    check_cannibal: bool = True,
    content_type: str = "article",
    brief: dict | None = None,
) -> dict:
    """Generate article via LLM and store as draft — سنگ تموم version."""
    project = repo.get_project(project_id) if project_id else None
    project_block = ""
    if project:
        try:
            meta = json.loads(project["metadata_json"] or "{}")
        except Exception:
            meta = {}
        project_block = f"""
پروژه: {project['name']} (slug={project['slug']})
دامنه: {project['domain'] or '—'}
صنعت: {project['industry'] or '—'}
یادداشت‌ها: {project['notes'] or '—'}
متادیتا: {json.dumps(meta, ensure_ascii=False, indent=2)}
"""

    # Cannibalization
    cannibal = []
    if check_cannibal:
        cannibal = check_cannibalization(project_id, topic)

    cannibal_block = ""
    if cannibal:
        cannibal_block = "⚠️ مقالات مشابه موجود (از Cannibalization جلوگیری کن — زاویه جدید بگیر):\n" + "\n".join(
            f"- {c['title']} (شباهت {c['similarity']})" for c in cannibal[:5]
        )
    else:
        cannibal_block = "هیچ مقاله مشابهی یافت نشد — موضوع جدید است."

    # Brief
    brief_block = ""
    if brief:
        brief_block = f"""
بریف محتوا:
{json.dumps(brief, ensure_ascii=False, indent=2)}
"""

    # GSC insights for this topic
    gsc_block = ""
    try:
        suggestions = suggest_topics_from_gsc(project_id=project_id, limit=5)
        related = [s for s in suggestions if _similarity(topic, s["topic"]) > 0.2]
        if related:
            gsc_block = "داده Search Console مرتبط:\n" + "\n".join(
                f"- {r['topic']}: {r['reason']}" for r in related[:3]
            )
    except Exception:
        pass

    user_prompt = f"""{project_block}

{brief_block}

موضوع درخواستی: {topic}
نوع محتوا: {content_type}
تعداد کلمات هدف: {target_words}

{cannibal_block}

{gsc_block}

لطفاً مقاله کامل را با ساختار JSON که در سیستم به تو گفته شد تولید کن. محتوا باید جامع، B2B-aware (اگر گیاهکده است)، با FAQ و CTA باشد.
برای گیاهکده: حتماً بخش «خرید عمده» و «کاربرد صنعتی» اضافه کن.
"""

    llm = get_provider()
    messages = [
        LLMMessage(role="system", content=CONTENT_SYSTEM),
        LLMMessage(role="user", content=user_prompt),
    ]
    try:
        result = llm.structured_output(messages, temperature=0.6, max_tokens=4000)
    except Exception as exc:
        log.warning("content.generate_failed", extra={"extra_fields": {"error": str(exc)}})
        result = {
            "title": topic[:70],
            "slug_en": topic.lower().replace(" ", "-")[:50],
            "outline": ["مقدمه", "فواید اصلی", "کاربردها", "نکات خرید", "سوالات متداول", "نتیجه‌گیری"],
            "content": f"# {topic}\n\nاین یک پیش‌نویس اولیه است که به دلیل خطای LLM به صورت خودکار ساخته شد. لطفاً آن را ویرایش کنید.\n\n## مقدمه\nموضوع {topic} یکی از موضوعات مهم در حوزه {project['name'] if project else 'کسب‌وکار'} است.\n\n## بدنه اصلی\nمحتوای جامع در اینجا قرار می‌گیرد...\n\n{project_block}",
            "excerpt": topic[:150],
            "faq": [{"q": f"{topic} چیست؟", "a": "توضیح کوتاه"}, {"q": f"فواید {topic} چیست؟", "a": "فواید زیاد"}],
            "image_prompt": f"Professional illustration about {topic}, high quality, 4k, detailed",
            "cta": "برای خرید عمده و استعلام قیمت تماس بگیرید",
            "meta_title": topic[:60],
            "meta_description": topic[:150],
            "focus_keyword": topic.split()[0] if topic else "محصول",
            "canonical_url": None,
            "word_count": 500,
            "tags": [topic],
            "content_type": content_type,
        }

    # Normalize
    title = (result.get("title") or topic)[:200]
    slug_en = (result.get("slug_en") or title.lower().replace(" ", "-"))[:120]
    outline = result.get("outline") or []
    content_text = result.get("content") or ""
    excerpt = result.get("excerpt") or ""
    faq = result.get("faq") or []
    image_prompt = result.get("image_prompt") or ""
    cta = result.get("cta") or ""
    meta_title = result.get("meta_title") or title[:60]
    meta_description = result.get("meta_description") or excerpt[:160]
    focus_keyword = result.get("focus_keyword") or ""
    canonical_url = result.get("canonical_url")
    word_count = int(result.get("word_count") or len(content_text.split()))
    tags = result.get("tags") or []

    draft = create_draft(
        project_id=project_id,
        topic=topic,
        title=title,
        slug_en=slug_en,
        outline=outline,
        content=content_text,
        excerpt=excerpt,
        faq=faq,
        image_prompt=image_prompt,
        cta=cta,
        meta_title=meta_title,
        meta_description=meta_description,
        focus_keyword=focus_keyword,
        canonical_url=canonical_url,
        word_count=word_count,
        status="draft",
        cannibalization=cannibal,
        seo_score=None,
        seo_notes=f"بررسی cannibalization: {len(cannibal)} مورد مشابه" if cannibal else "بدون ریسک cannibalization",
        created_by=created_by,
    )

    # Create task for tracking
    try:
        repo.create_task(
            title=f"بررسی و انتشار: {title}",
            project_id=project_id,
            description=f"پیش‌نویس محتوا برای موضوع «{topic}» تولید شد. تعداد کلمات: {fa_num(word_count)} — تگ‌ها: {', '.join(tags[:3])} — نیاز به تأیید.",
            priority="normal",
            source="content_agent",
        )
    except Exception:
        pass

    # Auto SEO audit
    try:
        from app.agents.seo_agent import audit_content
        audit = audit_content(draft["draft_uid"])
    except Exception:
        audit = None

    return {
        "draft": dict(draft),
        "cannibalization": cannibal,
        "seo_audit": audit,
        "brief": brief,
        "llm_result": result,
    }


def rewrite_for_seo(
    *,
    draft_uid: str,
    instructions: str = "بهینه‌سازی سئو",
) -> dict:
    """Rewrite existing draft for better SEO."""
    draft = get_draft(draft_uid)
    if not draft:
        raise ValueError(f"Draft not found: {draft_uid}")

    project_id = draft["project_id"]
    project = repo.get_project(project_id) if project_id else None

    user_prompt = f"""
مقاله موجود:
عنوان: {draft['title']}
محتوا: {draft['content'][:3000]}

دستور: {instructions}

لطفاً نسخه بهبودیافته را با همان ساختار JSON قبلی برگردان — محتوا را کامل‌تر، سئو شده‌تر و با چگالی کلمه کلیدی مناسب کن.
کلمه کلیدی: {draft['focus_keyword'] or '—'}
"""

    llm = get_provider()
    messages = [
        LLMMessage(role="system", content=CONTENT_SYSTEM),
        LLMMessage(role="user", content=user_prompt),
    ]
    try:
        result = llm.structured_output(messages, temperature=0.5, max_tokens=3500)
        # Update draft
        update_draft(
            draft_uid,
            title=result.get("title") or draft["title"],
            content=result.get("content") or draft["content"],
            meta_title=result.get("meta_title"),
            meta_description=result.get("meta_description"),
            word_count=int(result.get("word_count") or len((result.get("content") or "").split())),
            seo_notes=f"بازنویسی: {instructions}",
        )
        return {"draft": dict(get_draft(draft_uid)), "llm_result": result}
    except Exception as exc:
        log.warning("content.rewrite_failed", extra={"extra_fields": {"error": str(exc)}})
        raise


def publish_draft_to_wordpress(draft_uid: str, *, as_draft: bool = True) -> dict:
    """Create WordPress post from draft via approval gateway."""
    draft = get_draft(draft_uid)
    if not draft:
        raise ValueError(f"Draft not found: {draft_uid}")

    from app import approvals

    project_id = draft["project_id"]
    payload = {
        "project_id": project_id,
        "title": draft["title"],
        "content": draft["content"],
        "slug": draft["slug_en"],
        "excerpt": draft["excerpt"],
        "seo_title": draft["meta_title"],
        "seo_description": draft["meta_description"],
        "focus_keyword": draft["focus_keyword"],
        "canonical": draft["canonical_url"],
        "status": "draft" if as_draft else "publish",
    }

    action_type = "wordpress.create_draft" if as_draft else "wordpress.publish"

    res = approvals.request_action(
        action_type=action_type,
        title=f"{'پیش‌نویس' if as_draft else 'انتشار'}: {draft['title']}",
        summary=draft["excerpt"],
        payload=payload,
        requested_by=draft["created_by"],
        project_id=project_id,
        agent="content_agent",
    )

    if res.executed:
        update_draft(draft_uid, status="approved" if as_draft else "published", wordpress_post_id=None)
    else:
        update_draft(draft_uid, status="pending_approval")

    return {"action_uid": res.action_uid, "executed": res.executed, "message": res.message}


def get_content_performance(
    *,
    draft_uid: str | None = None,
    project_id: int | None = None,
) -> dict:
    """Get GSC performance for a content draft if URL matches."""
    if not draft_uid and not project_id:
        return {"error": "draft_uid or project_id required"}

    draft = None
    if draft_uid:
        draft = get_draft(draft_uid)
        if not draft:
            return {"error": "draft not found"}
        project_id = draft["project_id"]

    # Try to find GSC creds and check performance for this draft's URL or topic
    try:
        from app.integrations import store
        from app.integrations.google import gsc_query

        creds = None
        prop = None
        for pid in ([project_id] if project_id else []) + [None]:
            try:
                row = store.find("google_search_console", pid)
                if row:
                    creds = store.credentials("google_search_console", pid)
                    prop = creds.get("property_url")
                    break
            except Exception:
                pass

        if not creds or not prop:
            return {"error": "GSC not configured", "needs_setup": True}

        # If draft has wordpress_url, query for that page
        # For MVP, query for topic as query dimension
        topic = draft["topic"] if draft else ""
        if topic:
            data = gsc_query(creds, prop, dimensions=["query"], row_limit=20)
            # Filter for queries containing topic keywords
            rows = data.get("rows", [])
            related = [r for r in rows if any(w in (r.get("keys", [""])[0].lower()) for w in topic.lower().split()[:3])]
            return {
                "topic": topic,
                "related_queries": related[:10],
                "property": prop,
            }
        else:
            # Return overall project GSC data
            from app.integrations.google import get_project_google_data
            return get_project_google_data(gsc_creds=creds, gsc_property=prop, ga4_creds=None, ga4_property=None)

    except Exception as exc:
        return {"error": str(exc)}
