# نقشه‌ی راه و ارزیابی امکان‌پذیری Ali OS

> این سند پاسخ به خواسته‌های ۲۳گانه است: چه چیزی قابل پیاده‌سازی است، چقدر سخت است،
> چه وابستگی خارجی دارد و در چه فازی باید ساخته شود.

## ⚡️ وضعیت فعلی پروژه (به‌روزشده: ۲۰۲۶-۰۸-۲۷)

- [x] فیکس Mini App (احراز هویت خودکفا بدون telegram.org) — `app/miniapp/static/index.html` امروز به main اضافه شد
- [x] همین ROADMAP.md به مخزن اضافه شد
- [ ] (توصیه‌شده) UptimeRobot روی `https://ali-os.onrender.com/health` هر ۵ دقیقه = سرور همیشه بیدار
- [x] **فاز ۲ شروع شد** — Approval System سه‌سطحی + پرونده‌ی کامل پروژه (پایین را ببین)

### ✅ قدم ۱ فاز ۲ — انجام شد

**Approval System (§19)**
- جدول `pending_actions` با ریسک 🟢🟡🔴، وضعیت، شمارنده‌ی تأیید و انقضا (TTL)
- `app/approvals/risk.py` — جدول سیاست `action_type → ریسک`؛ اکشن ناشناخته **هرگز** 🟢 نمی‌شود
- `app/approvals/registry.py` — ثبت اجراکننده با `@executor("task.create")`
- `app/approvals/gateway.py` — تنها دروازه‌ی اجرای عملیات: 🟢 مستقیم، 🟡 یک تأیید، 🔴 دو تأیید
- دکمه‌های Inline تلگرام `[✅ تأیید] [❌ لغو]` + هندل `callback_query` در `/webhook`
- کارت تأیید بعد از تصمیم با `editMessageText` قفل می‌شود (audit در خود چت)
- محافظت‌ها: فقط درخواست‌دهنده تصمیم می‌گیرد، تصمیم دوباره ممکن نیست، انقضا، خطای
  اجراکننده در `failed` ثبت می‌شود، قطعی تلگرام تصمیم ثبت‌شده را برنمی‌گرداند
- `/approvals` = صف تأیید

**پرونده‌ی کامل پروژه (§2)**
- جداول `project_kpis` / `project_budget` / `project_people`
- `repo.project_dossier()` = هویت + KPI + بودجه (با جمع تفکیکی ارز) + افراد + Task باز +
  تصمیم‌ها + حافظه + اقدامات در انتظار تأیید
- `/dossier <پروژه>` یا «پرونده گیاهکده» در تلگرام + `GET /api/projects/<slug>/dossier`
- KPIهای اولیه‌ی giahkade / esqom / e-ferdowsi / netnova seed شد (مقدار واقعی در فاز ۳ از GSC/GA4)

**تست:** `python -m pytest tests -q` → ۲۴ تست سبز (بدون شبکه).

### ✅ قدم ۲ فاز ۲ — انجام شد

**اتصال‌ها و مدیریت Secret (§20)** — ورودی‌های لازم از داخل خود اپ گرفته می‌شود:
- جدول `integrations` (project_id، سرویس، credentials رمزنگاری‌شده با Fernet، وضعیت)
- `app/integrations/catalog.py` — کاتالوگ سرویس‌ها؛ **فرم‌های UI از روی همین ساخته می‌شوند**،
  پس افزودن سرویس جدید فقط تغییر داده است نه کد UI
- `app/integrations/crypto.py` — رمزنگاری Fernet؛ بدون `ENCRYPTION_KEY` ذخیره‌ی Secret
  **رد می‌شود** (به‌جای ذخیره‌ی ناامن)
- `app/integrations/testers.py` — تست زنده‌ی اتصال بعد از ذخیره
- تب «🔌 اتصال‌ها» در Mini App + دستور `/connections` در تلگرام
- Secretها هرگز کامل به کلاینت برنمی‌گردند (فقط `••••1234`)؛ ویرایش بدون تایپ دوباره‌ی رمز

**WordPress Agent (§3)**
- خواندن آزاد: `list_posts`، `list_categories`، `content_index` (ضد Cannibalization)
- نوشتن از دروازه‌ی تأیید: `create_draft`/`update_post` 🟡، `publish`/`delete_post` 🔴
- پشتیبانی از فیلدهای Rank Math (title/description/canonical/focus keyword) و زمان‌بندی

**سرویس‌های آماده:** وردپرس/ووکامرس، کانال تلگرام، SMTP، GSC، GA4
**مسدود (با دلیل شفاف در UI):** Google Ads، Google Business Profile، Instagram

**تست:** ۵۲ تست سبز — شامل رمزنگاری، ماسک‌شدن، merge نکردن رمز قدیمی، چرخش کلید،
و اینکه `wordpress.publish` بدون دو تأیید اجرا نمی‌شود.

> قدم بعدی فاز ۲: CRM پایه + PM Agent (گزارش صبحگاهی) + Content Agent.

---

## ارزیابی کلی

**حدود ۹۰٪ کل خواسته‌ها قابل پیاده‌سازی کامل است** — البته نه یکجا؛ در ۴ فاز.
حدود **۷۰-۷۵٪ در فازهای ۲ و ۳** (چند هفته کار متمرکز) بدست می‌آید.

محدودیت‌های واقعی فقط در این موارد است:
- **Google Ads API**: نیاز به Developer Token دارد که تأییدش درخواستی و زمان‌بر است
- **Instagram/LinkedIn/X**: محدودیت سیاستی API (نه فنی) — تلگرام ۱۰۰٪ آزاد است
- **Google Business Profile**: دسترسی API نیاز به فرم درخواست دارد
- تأخیر ذاتی داده‌ی Search Console (۲-۳ روز) — محدودیت گوگل است، نه ما

## جدول ارزیابی ۲۳ بخش

| # | بخش | امکان | سختی | وابستگی خارجی | فاز |
|---|------|-------|------|----------------|-----|
| 1 | هسته اصلی (شناخت، حافظه، تصمیمات، تأیید) | ۱۰۰٪ | متوسط | — | ۲ |
| 2 | پرونده‌ی کامل پروژه (KPI، بودجه، افراد،…) | ۱۰۰٪ | آسان | — | ۲ |
| 3 | اتصال WordPress/WooCommerce | ۹۵٪ | متوسط | Application Password مشتری | ۲ |
| 4 | Google Search Console | ۹۰٪ | متوسط | OAuth گوگل (یک‌بار راه‌اندازی) | ۳ |
| 5 | Google Analytics GA4 | ۹۰٪ | متوسط | همان OAuth | ۳ |
| 6 | Google Ads | ۷۰٪ | سخت | Developer Token (تأیید گوگل) | ۴+ |
| 7 | Google Business Profile | ۷۵٪ | سخت | فرم درخواست API | ۴+ |
| 8 | SEO Agent | ۹۰٪ | متوسط | داده‌ی ۴ و ۵ | ۳ |
| 9 | Content Agent | ۹۰٪ | متوسط | کیفیت LLM | ۲-۳ |
| 10 | Social Media | ۶۰٪ | سخت* | *تلگرام ۱۰۰٪؛ اینستاگرام نیاز به Business+اپ فیسبوک؛ لینکدین/X محدود | ۴+ |
| 11 | PM Agent (صبحگاهی، اولویت‌بندی) | ۹۵٪ | متوسط | Scheduler (زیر) | ۲ |
| 12 | Business Analyst | ۹۵٪ | متوسط | داده‌ی داخلی CRM/مالی | ۳ |
| 13 | Sales Agent | ۹۵٪ | آسان-متوسط | — | ۳ |
| 14 | CRM شخصی | ۱۰۰٪ | آسان | — | ۲-۳ |
| 15 | Financial Agent | ۹۵٪ | متوسط | — | ۴ |
| 16 | Automation (گزارش صبحگاهی و…) | ۹۰٪ | متوسط | Cron خارجی (زیر) | ۳ |
| 17 | Monitoring Agent | ۹۰٪ | متوسط | — | ۳-۴ |
| 18 | Notification System | ۱۰۰٪ | آسان | — | ۲ |
| 19 | Approval System (۳ سطح) | ۱۰۰٪ | متوسط | — | **۲ (اول!)** |
| 20 | Permission/Secret Management | ۹۵٪ | متوسط | — | ۲ |
| 21 | Multi-Project Architecture | ۹۵٪ | متوسط | — | ۲ |
| 22 | معماری چند-Agent (Master=Orchestrator) | ۹۰٪ | متوسط-سخت | — | ۲→۴ تدریجی |
| 23 | چرخه‌ی طلایی Read→…→Remember | ۱۰۰٪ | متوسط | — | ۲ |

## نکات فنی مهم هر اتصال

### WordPress (فاز ۲ — بهترین نقطه‌ی شروع)
- REST API رسمی + Basic Auth با **Application Password** (قابل لغو، بدون رمز اصلی) — همه‌ی
  کارهای فهرست‌شده (مقاله، دسته، تصویر، وضعیت draft/scheduled، ویرایش…) پشتیبانی می‌شود
- فیلدهای Rank Math (title/description/canonical/robots/schema) از طریق meta در REST قابل
  خواندن/نوشتن‌اند؛ schema و لینک‌های داخلی با fetch صفحات و پارس JSON-LD بررسی می‌شوند

### Google (فاز ۳)
- یک Google Cloud Project + OAuth Consent + refresh token برای Search Console و GA4 کافی است
- GSC: `searchanalytics.query` با ابعاد query/page/device/country — سهمیه‌ی روزانه کافی است؛
  داده ۲-۳ روز تأخیر دارد
- GA4: Data API (`runReport`) — همه‌ی متریک‌های خواسته‌شده موجودند

### Scheduler روی هاست رایگان (فاز ۳)
- Render رایگان cron داخلی ندارد؛ راه‌حل: **cron-job.org یا GitHub Actions** که هر صبح یک
  endpoint امن (`/internal/cron?secret=...`) را صدا بزند → گزارش صبحگاهی در تلگرام
- جایگزین: APScheduler داخل همان worker (با پینگ keep-alive که UptimeRobot می‌دهد)

### Approval System — باید در فاز ۲ اول ساخته شود
- جدول `pending_actions` (نوع عملیات، payload، سطح ریسک 🟢🟡🔴، وضعیت، انقضا)
- دکمه‌های Inline تلگرام `[تأیید] [لغو]` + هندل `callback_query` در webhook
- هیچ Agentی اجازه‌ی اجرای عملیات 🟡/🔴 بدون رکورد pending تأییدشده نداشته باشد

### امنیت Secretها
- جدول `integrations` (project_id, نوع سرویس، credentials رمزنگاری‌شده با Fernet، وضعیت اتصال)
- کلید رمزنگاری از env — هیچ secretی در کد/GITHUB (همین اصل الان هم رعایت شده)

## فازبندی پیشنهادی

**فاز ۲ — ستون فقرات (بیشترین ارزش، بدون وابستگی خارجی):**
Approval System + پرونده‌ی کامل پروژه + CRM پایه + WordPress Agent + PM Agent +
Notification + Multi-project context + جدول integrations — *پوشش ~۴۵٪ کل خواسته‌ها*

**فاز ۳ — داده‌ی واقعی گوگل:**
OAuth یک‌بار + Search Console + GA4 + SEO Agent + Content Agent کامل +
Automation/گزارش صبحگاهی + Monitoring + Sales/BA — *پوشش تا ~۷۵٪*

**فاز ۴ — بلوغ:**
Financial + Business Analyst عمیق + Google Ads + GBP + Social (از تلگرام شروع) — *تا ~۹۰٪*

**باقی‌مانده (~۱۰٪):** قابلیت‌های محدودشده‌ی سیاستی API سوشال‌مدیا و تأخیر ذاتی GSC.

## گام بعدی پیشنهادی وقتی برگشتی

جلسه‌ی کدنویسی جدید باز کن و بگو: «فاز ۲ را شروع کن — اول Approval System و پرونده‌ی
کامل پروژه». زیرساخت فعلی (MasterAgent، LLMProvider، repositories، Turso، Mini App)
دقیقاً برای همین توسعه طراحی شده و فاز ۲ بدون هیچ تأیید خارجی قابل ساخت است.
