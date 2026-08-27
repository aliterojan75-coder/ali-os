"""Seed the first real projects and memories (§11–17, §50).

Idempotent: safe to run on every startup. It checks each project slug before
inserting.
"""
from __future__ import annotations

from app import db, repositories as repo
from app.logging_config import get_logger

log = get_logger("seed")

PROJECTS = [
    {
        "slug": "netnova",
        "name": "Net Nova",
        "domain": "netnova.ir",
        "industry": "دیجیتال مارکتینگ",
        "notes": "مجموعه اصلی علی: طراحی سایت WordPress/WooCommerce، SEO، تولید محتوا، استراتژی کسب‌وکار.",
        "metadata": {"services": ["wordpress", "woocommerce", "seo", "content", "consulting"]},
    },
    {
        "slug": "giahkade",
        "name": "گیاهکده",
        "domain": None,
        "industry": "فروش محصولات طبیعی و گیاهی",
        "notes": (
            "پروژه تست اصلی MVP. تمرکز محتوا بر B2B و خریدار عمده در کنار مصرف‌کننده. "
            "محصولات کلیدی: عرق نعناع، گلاب، بهارنارنج، روغن کنجد/زیتون، پودر سیر/پیاز/گوجه، پیاز خشک. "
            "قوانین: قبل از موضوع جدید Content Index بررسی شود؛ جلوگیری از Cannibalization؛ "
            "مقالات جامع ~۲۰۰۰ کلمه؛ English slug، FAQ، Image Prompt، CTA خرید."
        ),
        "metadata": {
            "products": ["عرق نعناع", "گلاب", "عرق بهارنارنج", "روغن کنجد", "روغن زیتون",
                         "پودر سیر سفید", "پودر پیاز", "پودر گوجه", "پیاز خشک"],
            "content_rules": {
                "check_content_index_first": True,
                "avoid_cannibalization": True,
                "target_words": 2000,
                "b2b_aware": True,
                "needs_faq": True,
                "needs_image_prompt": True,
                "english_slug": True,
            },
            "existing_articles": [
                "گلاب را با چی بخوریم؟ ترکیب‌های خوش‌طعم گلاب برای نوشیدنی و دسر",
                "فرق روغن زیتون با بو و بی‌بو چیست؟ کدام را انتخاب کنیم؟",
                "عرق نعناع را با چی بخوریم؟ ترکیب‌های مناسب برای مصرف روزانه",
            ],
        },
    },
    {
        "slug": "e-ferdowsi",
        "name": "E-Ferdowsi",
        "domain": "e-ferdowsi.ir",
        "industry": "فروشگاه دیجیتال / WooCommerce",
        "notes": "WordPress + WooCommerce + Elementor. Landing Page، FOMO، Login/Register، SMS auth. محصول شاخص: بسته قدرت نامه‌نگاری.",
        "metadata": {"stack": ["wordpress", "woocommerce", "elementor"]},
    },
    {
        "slug": "esqom",
        "name": "امداد سرویس قم",
        "domain": "esqom.ir",
        "industry": "تعمیرات لوازم خانگی (قم)",
        "notes": (
            "هدف SEO Recovery: بازیابی رتبه‌ها، افزایش Organic Traffic/CTR/Lead. "
            "Search Console حدود ۳ ماه مشکل داشته. Core Web Vitals Failed (LCP~3s, INP~83ms, CLS مشکل‌دار, FCP~2.3s, TTFB~1.3s). "
            "رتبه‌های نمونه مرداد ۱۴۰۵: تعمیر یخچال مابه~۴، وایت~۲، وستینگهاوس~۳."
        ),
        "metadata": {
            "project_mode": "SEO Recovery OS",
            "core_web_vitals": {"lcp_ms": 3000, "inp_ms": 83, "cls": "issue", "fcp_ms": 2300, "ttfb_ms": 1300},
            "rankings": {"تعمیر یخچال مابه در قم": 4, "تعمیر یخچال وایت در قم": 2, "تعمیر یخچال وستینگهاوس در قم": 3},
        },
    },
    {
        "slug": "cropexport",
        "name": "CropExport",
        "domain": "cropexport.com",
        "industry": "صادرات محصولات کشاورزی",
        "notes": (
            "چندزبانه (فارسی/English/Arabic). محتوا فارسی پایه ولی هر زبان SEO مستقل می‌خواهد، نه ترجمه صرف. "
            "نمونه: هندوانه (B32 Pro، گرد خطی باراکا، گرد مشکی یونیژن)؛ برداشت اسفند-مرداد؛ MOQ~25 تن؛ بسته‌بندی Carton/Basket/Pallet."
        ),
        "metadata": {"languages": ["fa", "en", "ar"], "no_direct_translation": True, "moq_tons": 25},
    },
    {
        "slug": "abadgaran",
        "name": "آبادگران فرآیند تجدید",
        "domain": None,
        "industry": "B2B صنعتی / بازیافت",
        "notes": "خرید فیلم رادیولوژی، بردهای الکترونیکی ضایعاتی، فلزات گران‌بها، کاتالیست؛ استخراج نقره/طلا/پالادیوم/پلاتین/رودیوم؛ بازیافت صنعتی و انتقال دانش فنی. تمرکز: Branding، Logo، Brand Colors، Website، Landing Page، Industrial B2B positioning.",
        "metadata": {"type": "b2b_industrial"},
    },
    {
        "slug": "sir-siah",
        "name": "Sir-Siah / لوآ Looa",
        "domain": "sir-siah.ir",
        "industry": "Black Garlic",
        "notes": "برند لوآ / Looa. کارهای مرتبط: Branding، طراحی، تغییر رنگ، محتوا.",
        "metadata": {"brand": "Looa"},
    },
]


USER_MEMORIES = [
    ("preference", "user", "زبان اصلی تعامل فارسی است؛ کد/API/مستندات فنی می‌توانند انگلیسی باشند.", 1.0, "explicit_user_instruction"),
    ("preference", "user", "سبک کاری نتیجه‌محور و علاقه‌مند به اتوماسیون/سیستم‌سازی؛ خروجی باید کاربردی و قابل اجرا باشد نه تئوری.", 0.98, "explicit_user_instruction"),
    ("work_rule", "user", "برای اقدامات مهم: Claim → Evidence → Reasoning → Decision → Action → Result.", 0.99, "explicit_user_instruction"),
    ("work_rule", "user", "اگر پاسخ در Memory موجود نیست، اول تحقیق کن؛ بر اساس Memory قدیمی برای داده‌های متغیر جواب قطعی نده (ضد Hallucination).", 0.95, "explicit_user_instruction"),
    ("work_rule", "user", "هیچ Secret در کد قرار نمی‌گیرد؛ کلیدها از Environment/Secret خوانده می‌شوند. اقدامات High Risk نیازمند تأیید علی است.", 0.99, "explicit_user_instruction"),
]


# ─── Starter project dossier data (§2) ──────────────────────────────────────
# Only KPI *definitions* (targets) are seeded — real current values arrive in
# Phase 3 from Search Console / GA4. Seeding is idempotent by (project, name).
PROJECT_KPIS = {
    "giahkade": [
        {"name": "مقالات منتشرشده", "target_value": 12, "unit": "مقاله", "period": "monthly"},
        {"name": "ترافیک ارگانیک", "target_value": 10000, "unit": "بازدید", "period": "monthly"},
        {"name": "نرخ تبدیل B2B", "target_value": 3, "unit": "٪", "period": "monthly"},
    ],
    "esqom": [
        {"name": "LCP", "target_value": 2500, "unit": "ms", "period": "weekly", "direction": "down"},
        {"name": "INP", "target_value": 200, "unit": "ms", "period": "weekly", "direction": "down"},
        {"name": "لیدهای ورودی", "target_value": 30, "unit": "لید", "period": "monthly"},
        {"name": "CTR ارگانیک", "target_value": 4, "unit": "٪", "period": "monthly"},
    ],
    "e-ferdowsi": [
        {"name": "فروش ماهانه", "target_value": 100_000_000, "unit": "تومان", "period": "monthly"},
        {"name": "نرخ تبدیل فروشگاه", "target_value": 2, "unit": "٪", "period": "monthly"},
    ],
    "netnova": [
        {"name": "مشتریان فعال", "target_value": 10, "unit": "مشتری", "period": "monthly"},
        {"name": "درآمد ماهانه", "target_value": 200_000_000, "unit": "تومان", "period": "monthly"},
    ],
}

PROJECT_PEOPLE = {
    "netnova": [
        {"name": "علی", "role": "مالک / تصمیم‌گیرنده نهایی",
         "responsibility": "استراتژی، تأیید اقدامات پرخطر", "is_internal": True},
        {"name": "Ali OS", "role": "Chief of Staff (AI)",
         "responsibility": "تحلیل، اجرا، پیگیری، گزارش", "is_internal": True},
    ],
}


def _seed_dossier() -> None:
    for slug, kpis in PROJECT_KPIS.items():
        project = repo.get_project(slug)
        if not project:
            continue
        for k in kpis:
            exists = db.query_one(
                "SELECT id FROM project_kpis WHERE project_id=? AND name=?",
                (project["id"], k["name"]),
            )
            if exists:
                continue
            repo.add_kpi(
                project_id=project["id"], name=k["name"],
                target_value=k.get("target_value"), unit=k.get("unit"),
                period=k.get("period", "monthly"), direction=k.get("direction", "up"),
            )
    for slug, people in PROJECT_PEOPLE.items():
        project = repo.get_project(slug)
        if not project:
            continue
        for person in people:
            exists = db.query_one(
                "SELECT id FROM project_people WHERE project_id=? AND name=?",
                (project["id"], person["name"]),
            )
            if exists:
                continue
            repo.add_person(project_id=project["id"], **person)


def seed_all() -> None:
    db.init_db()
    for p in PROJECTS:
        existing = repo.get_project(p["slug"])
        if existing:
            continue
        repo.create_project(
            p["slug"], p["name"],
            domain=p.get("domain"),
            industry=p.get("industry"),
            notes=p.get("notes"),
            metadata=p.get("metadata", {}),
        )
        log.info("seed.project", extra={"extra_fields": {"slug": p["slug"], "name": p["name"]}})

    for m in USER_MEMORIES:
        mtype, scope, content, conf, source = m
        existing = db.query_one(
            "SELECT id FROM memories WHERE memory_type=? AND scope=? AND content=?",
            (mtype, scope, content),
        )
        if existing:
            continue
        repo.add_memory(
            memory_type=mtype, scope=scope, content=content,
            confidence=conf, source=source,
        )
    _seed_dossier()
    log.info("seed.complete", extra={"extra_fields": {"projects": len(PROJECTS), "memories": len(USER_MEMORIES)}})


if __name__ == "__main__":
    seed_all()
