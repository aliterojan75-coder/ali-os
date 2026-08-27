"""Catalog of connectable services (§3, §4–7, §10, §20).

This is the single source of truth for "what can Ali OS connect to and what
does it need from Ali". The Mini App renders its connection forms directly
from this catalog, so adding a new service is a data change here — no UI work.

Each field declares:
    key        machine name stored in the credentials blob
    label      Persian label shown to Ali
    type       text | password | url | email | textarea | select
    secret     True → encrypted at rest and never returned to the client
    required   blocks saving when empty
    help       short hint rendered under the input
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Field:
    key: str
    label: str
    type: str = "text"
    secret: bool = False
    required: bool = True
    help: str = ""
    placeholder: str = ""
    options: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "type": self.type,
            "secret": self.secret, "required": self.required,
            "help": self.help, "placeholder": self.placeholder,
            "options": self.options,
        }


@dataclass
class Service:
    slug: str
    name: str
    icon: str
    category: str
    phase: int
    summary: str
    fields: list[Field]
    guide: list[str] = field(default_factory=list)
    can_test: bool = True
    available: bool = True
    blocked_reason: str = ""
    per_project: bool = True

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "name": self.name, "icon": self.icon,
            "category": self.category, "phase": self.phase,
            "summary": self.summary, "guide": self.guide,
            "can_test": self.can_test, "available": self.available,
            "blocked_reason": self.blocked_reason,
            "per_project": self.per_project,
            "fields": [f.to_dict() for f in self.fields],
        }


SERVICES: list[Service] = [
    # ── Phase 2: available right now ────────────────────────────────────────
    Service(
        slug="wordpress",
        name="WordPress / WooCommerce",
        icon="🌐",
        category="سایت",
        phase=2,
        summary="انتشار و ویرایش مقاله، دسته‌بندی، تصویر شاخص، فیلدهای Rank Math.",
        fields=[
            Field("site_url", "آدرس سایت", "url",
                  placeholder="https://giahkade.com",
                  help="آدرس کامل با https — بدون /wp-admin"),
            Field("username", "نام کاربری وردپرس", "text",
                  placeholder="ali",
                  help="نام کاربری کاربری که Application Password برایش ساختی"),
            Field("app_password", "Application Password", "password", secret=True,
                  placeholder="xxxx xxxx xxxx xxxx xxxx xxxx",
                  help="رمز اصلی را وارد نکن. در پیشخوان: کاربران → پروفایل → "
                       "Application Passwords → یک رمز جدید بساز. هر زمان بخواهی "
                       "قابل لغو است."),
        ],
        guide=[
            "وارد پیشخوان وردپرس شو: کاربران → پروفایل شخصی",
            "پایین صفحه بخش «Application Passwords» را پیدا کن",
            "یک نام مثل «Ali OS» بنویس و روی «Add New Application Password» بزن",
            "رمز ۲۴ کاراکتری نمایش‌داده‌شده را کپی کن (فقط یک بار نشان داده می‌شود)",
            "همان را در فیلد بالا بگذار — رمز اصلی حساب هرگز لازم نیست",
        ],
    ),
    Service(
        slug="telegram_channel",
        name="کانال تلگرام",
        icon="📣",
        category="شبکه اجتماعی",
        phase=2,
        summary="انتشار خودکار پست در کانال. تلگرام هیچ محدودیت سیاستی ندارد.",
        fields=[
            Field("channel_id", "شناسه کانال", "text",
                  placeholder="@my_channel یا -1001234567890",
                  help="بات باید ادمین کانال با دسترسی ارسال پیام باشد"),
        ],
        guide=[
            "بات Ali OS را به کانال اضافه کن",
            "به بات دسترسی ادمین با اجازه‌ی «ارسال پیام» بده",
            "شناسه‌ی کانال (@username یا آی‌دی عددی) را اینجا وارد کن",
        ],
    ),
    Service(
        slug="smtp",
        name="ایمیل (SMTP)",
        icon="✉️",
        category="اعلان",
        phase=2,
        summary="ارسال گزارش و اعلان از طریق ایمیل.",
        per_project=False,
        fields=[
            Field("host", "سرور SMTP", "text", placeholder="smtp.gmail.com"),
            Field("port", "پورت", "text", placeholder="587", required=False,
                  help="معمولاً 587 برای TLS یا 465 برای SSL"),
            Field("username", "نام کاربری", "text", placeholder="you@example.com"),
            Field("password", "رمز عبور", "password", secret=True,
                  help="برای Gmail حتماً App Password بساز، نه رمز اصلی حساب"),
            Field("from_email", "ارسال از", "email", required=False,
                  placeholder="ali@netnova.ir"),
        ],
    ),

    # ── Phase 3: needs one-time Google OAuth ────────────────────────────────
    Service(
        slug="google_search_console",
        name="Google Search Console",
        icon="🔍",
        category="گوگل",
        phase=3,
        summary="کوئری‌ها، کلیک، ایمپرشن، CTR و پوزیشن. داده ۲-۳ روز تأخیر دارد.",
        fields=[
            Field("property_url", "آدرس Property", "url",
                  placeholder="https://giahkade.com/",
                  help="دقیقاً همان‌طور که در Search Console ثبت شده"),
            Field("client_id", "OAuth Client ID", "text",
                  help="از Google Cloud Console → APIs & Services → Credentials"),
            Field("client_secret", "OAuth Client Secret", "password", secret=True),
            Field("refresh_token", "Refresh Token", "password", secret=True,
                  help="یک‌بار ساخته می‌شود و برای همیشه معتبر است"),
        ],
        guide=[
            "در Google Cloud Console یک پروژه بساز",
            "Search Console API را فعال کن",
            "یک OAuth Client از نوع Desktop بساز و Client ID/Secret را بردار",
            "با اسکریپت `python -m app.tools.google_oauth` یک Refresh Token بگیر",
        ],
    ),
    Service(
        slug="google_analytics",
        name="Google Analytics (GA4)",
        icon="📈",
        category="گوگل",
        phase=3,
        summary="کاربر، سشن، نرخ تبدیل، کانال ورودی و رفتار صفحه.",
        fields=[
            Field("property_id", "GA4 Property ID", "text", placeholder="123456789",
                  help="در GA4: Admin → Property Settings"),
            Field("client_id", "OAuth Client ID", "text"),
            Field("client_secret", "OAuth Client Secret", "password", secret=True),
            Field("refresh_token", "Refresh Token", "password", secret=True),
        ],
        guide=[
            "همان پروژه‌ی Google Cloud بالا را استفاده کن",
            "Google Analytics Data API را فعال کن",
            "Property ID عددی را از تنظیمات GA4 بردار",
        ],
    ),

    # ── Phase 4+: blocked on external approval ──────────────────────────────
    Service(
        slug="google_ads",
        name="Google Ads",
        icon="💸",
        category="گوگل",
        phase=4,
        summary="کمپین، هزینه، کلیک و ROAS.",
        available=False,
        blocked_reason="نیازمند Developer Token است که تأییدش توسط گوگل زمان‌بر و "
                       "درخواستی است. فرم آماده است؛ به‌محض گرفتن توکن فعال می‌شود.",
        fields=[
            Field("customer_id", "Customer ID", "text", placeholder="123-456-7890"),
            Field("developer_token", "Developer Token", "password", secret=True),
            Field("client_id", "OAuth Client ID", "text"),
            Field("client_secret", "OAuth Client Secret", "password", secret=True),
            Field("refresh_token", "Refresh Token", "password", secret=True),
        ],
    ),
    Service(
        slug="google_business",
        name="Google Business Profile",
        icon="📍",
        category="گوگل",
        phase=4,
        summary="نظرات، جستجوی محلی و اطلاعات کسب‌وکار.",
        available=False,
        blocked_reason="دسترسی به API نیازمند پر کردن فرم درخواست و تأیید گوگل است.",
        fields=[
            Field("location_id", "Location ID", "text"),
            Field("client_id", "OAuth Client ID", "text"),
            Field("client_secret", "OAuth Client Secret", "password", secret=True),
            Field("refresh_token", "Refresh Token", "password", secret=True),
        ],
    ),
    Service(
        slug="instagram",
        name="Instagram",
        icon="📸",
        category="شبکه اجتماعی",
        phase=4,
        summary="انتشار پست و خواندن آمار.",
        available=False,
        blocked_reason="نیازمند حساب Business، صفحه‌ی فیسبوک متصل و اپ تأییدشده‌ی "
                       "Meta است — محدودیت سیاستی، نه فنی.",
        fields=[
            Field("ig_user_id", "Instagram User ID", "text"),
            Field("access_token", "Access Token", "password", secret=True),
        ],
    ),
]

BY_SLUG: dict[str, Service] = {s.slug: s for s in SERVICES}


def get(slug: str) -> Service | None:
    return BY_SLUG.get(slug)


def as_list() -> list[dict]:
    return [s.to_dict() for s in SERVICES]


def validate(slug: str, values: dict[str, Any]) -> tuple[dict, list[str]]:
    """Keep only known fields and report missing required ones."""
    service = get(slug)
    if service is None:
        return {}, [f"سرویس ناشناخته: {slug}"]
    cleaned: dict[str, Any] = {}
    errors: list[str] = []
    for f in service.fields:
        raw = values.get(f.key)
        value = ("" if raw is None else str(raw)).strip()
        if not value:
            if f.required:
                errors.append(f"«{f.label}» الزامی است")
            continue
        if f.type == "url" and not value.startswith(("http://", "https://")):
            errors.append(f"«{f.label}» باید با http:// یا https:// شروع شود")
            continue
        cleaned[f.key] = value
    return cleaned, errors


def secret_keys(slug: str) -> set[str]:
    service = get(slug)
    return {f.key for f in service.fields if f.secret} if service else set()
