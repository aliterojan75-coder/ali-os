"""Content Agent (§9) — generate articles with SEO awareness.

- Checks content_index to avoid cannibalization (گیاهکده rule)
- Generates structured article via LLM (title, slug_en, outline, content, FAQ, image_prompt, CTA, meta)
- Stores in content_drafts and optionally creates WordPress draft via approval gateway
"""

from __future__ import annotations

import json
from typing import Any

from app import db, repositories as repo
from app.content.repository import create_draft, update_draft, get_draft
from app.llm import LLMMessage, get_provider
from app.logging_config import get_logger
from app.utils.jalali import fa_num

log = get_logger("content_agent")

CONTENT_SYSTEM = """تو یک متخصص تولید محتوا و سئو برای پروژه‌های Ali OS هستی.

قوانین قطعی:
- محتوا باید فارسی روان، نتیجه‌محور و قابل اجرا باشد (نه تئوری کلی)
- برای پروژه گیاهکده: تمرکز B2B + مصرف‌کننده، از Cannibalization جلوگیری کن، مقالات جامع ~۲۰۰۰ کلمه، FAQ، Image Prompt، CTA خرید
- برای CropExport: چندزبانه بودن را در نظر بگیر، MOQ، بسته‌بندی، ارقام محصول
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
  "word_count": 1800
}

اگر اطلاعات کافی نداری، با همین ساختار ولی با محتوای حداقلی برگردان — هرگز JSON نامعتبر نده.
"""


def _similarity(a: str, b: str) -> float:
    """Very small Jaccard similarity on word sets — for cannibalization check."""
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def check_cannibalization(project_id: int | None, new_title: str, existing_limit: int = 100) -> list[dict]:
    """Check new title against existing content_index (WordPress or content_drafts)."""
    candidates: list[dict] = []

    # Check content_drafts
    try:
        rows = db.query_all(
            "SELECT title, slug_en FROM content_drafts WHERE project_id IS ? OR project_id=? ORDER BY updated_at DESC LIMIT ?",
            (project_id, project_id, existing_limit) if project_id is not None else (None, None, existing_limit),
        )
        # Actually need proper handling for NULL — simplify
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

    # Check WordPress content_index if integration exists
    try:
        from app.agents.wordpress import content_index
        wp_posts = content_index(project_id, limit=existing_limit)
        for p in wp_posts:
            sim = _similarity(new_title, p.get("title") or "")
            if sim > 0.35:
                candidates.append({"title": p.get("title"), "slug": p.get("slug"), "similarity": round(sim, 2), "source": "wordpress", "link": p.get("link")})
    except Exception:
        pass

    # Sort by similarity desc
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates[:10]


def generate_article(
    *,
    topic: str,
    project_id: int | None = None,
    created_by: int | None = None,
    target_words: int = 2000,
    check_cannibal: bool = True,
) -> dict:
    """Generate article via LLM and store as draft."""
    project = repo.get_project(project_id) if project_id else None
    project_block = ""
    if project:
        import json as _json
        try:
            meta = _json.loads(project["metadata_json"] or "{}")
        except Exception:
            meta = {}
        project_block = f"""
پروژه: {project['name']} (slug={project['slug']})
دامنه: {project['domain'] or '—'}
صنعت: {project['industry'] or '—'}
یادداشت‌ها: {project['notes'] or '—'}
متادیتا: {_json.dumps(meta, ensure_ascii=False, indent=2)}
"""

    # Cannibalization check
    cannibal = []
    if check_cannibal:
        cannibal = check_cannibalization(project_id, topic)

    cannibal_block = ""
    if cannibal:
        cannibal_block = "⚠️ مقالات مشابه موجود (از Cannibalization جلوگیری کن):\n" + "\n".join(
            f"- {c['title']} (شباهت {c['similarity']})" for c in cannibal[:5]
        )
    else:
        cannibal_block = "هیچ مقاله مشابهی یافت نشد — موضوع جدید است."

    user_prompt = f"""{project_block}

موضوع درخواستی: {topic}

{cannibal_block}

تعداد کلمات هدف: {target_words}

لطفاً مقاله کامل را با ساختار JSON که در سیستم به تو گفته شد تولید کن. محتوا باید جامع، B2B-aware (اگر گیاهکده است)، با FAQ و CTA باشد.
"""

    llm = get_provider()
    messages = [
        LLMMessage(role="system", content=CONTENT_SYSTEM),
        LLMMessage(role="user", content=user_prompt),
    ]
    try:
        result = llm.structured_output(messages, temperature=0.5, max_tokens=3000)
    except Exception as exc:
        log.warning("content.generate_failed", extra={"extra_fields": {"error": str(exc)}})
        # Fallback minimal draft
        result = {
            "title": topic[:70],
            "slug_en": topic.lower().replace(" ", "-")[:50],
            "outline": ["مقدمه", "بدنه اصلی", "نتیجه‌گیری"],
            "content": f"# {topic}\n\nاین یک پیش‌نویس اولیه است که به دلیل خطای LLM به صورت خودکار ساخته شد. لطفاً آن را ویرایش کنید.\n\nموضوع: {topic}\n\n{project_block}",
            "excerpt": topic[:150],
            "faq": [{"q": f"{topic} چیست؟", "a": "توضیح کوتاه"}],
            "image_prompt": f"Illustration about {topic}, professional, high quality",
            "cta": "برای اطلاعات بیشتر تماس بگیرید",
            "meta_title": topic[:60],
            "meta_description": topic[:150],
            "focus_keyword": topic.split()[0] if topic else "محصول",
            "canonical_url": None,
            "word_count": 300,
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

    # Also create a task for tracking?
    try:
        repo.create_task(
            title=f"بررسی و انتشار: {title}",
            project_id=project_id,
            description=f"پیش‌نویس محتوا برای موضوع «{topic}» تولید شد. تعداد کلمات: {fa_num(word_count)} — نیاز به تأیید.",
            priority="normal",
            source="content_agent",
        )
    except Exception:
        pass

    return {
        "draft": dict(draft),
        "cannibalization": cannibal,
        "llm_result": result,
    }


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

    # We need requested_by — use created_by from draft
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
