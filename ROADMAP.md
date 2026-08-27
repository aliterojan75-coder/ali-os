# نقشه‌ی راه و ارزیابی امکان‌پذیری Ali OS

> این سند پاسخ به خواسته‌های ۲۳گانه است: چه چیزی قابل پیاده‌سازی است، چقدر سخت است،
> چه وابستگی خارجی دارد و در چه فازی باید ساخته شود.

## ⚡️ وضعیت فعلی پروژه (به‌روزشده: ۲۰۲۶-۰۸-۲۷ — فاز ۲ کامل شد)

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

### ✅ قدم ۳ فاز ۲ — بازطراحی رابط کاربری

**داشبورد از یک لیست متنی به یک پنل تحلیلی تبدیل شد:**
- `app/miniapp/analytics.py` — یک endpoint (`/api/analytics`) که همه‌ی داده‌ی
  نمودارها را یکجا می‌دهد: روند ۱۴ روزه، هیت‌مپ ۸ هفته، تفکیک وضعیت/اولویت،
  خلاصه‌ی تأییدها، سلامت پروژه‌ها و KPIها
- `app/miniapp/static/charts.js` — کتابخانه‌ی کوچک SVG (نمودار خطی، دونات،
  گیج، نوار افقی، هیت‌مپ، نوار انباشته) با انیمیشن ورود
- **چرا SVG و نه Chart.js؟** همان دلیلی که فونت در این پروژه non-blocking لود
  می‌شود: روی شبکه‌هایی که CDN/telegram.org در دسترس نیست، داشبورد نباید نصفه
  بماند. SVG درون‌خطی = صفر وابستگی، آفلاین، سریع
- ناوبری ۶ تبی: خلاصه / تسک‌ها / پروژه‌ها / **تأیید** / اتصال / بیشتر
- شیت پرونده‌ی پروژه با گیج KPI و نوار مصرف بودجه
- اسکلت لودینگ به‌جای اسپینر، Haptic، بج شمارنده‌ی تأیید، اعداد فارسی

**سه باگ واقعی که تست headless لو داد:**
1. مسیر `/static/charts.js` را روت پیش‌فرض Flask می‌دزدید (به `app/static`
   اشاره می‌کرد که وجود ندارد) → `static_folder=None`
2. اگر شبکه `telegram.org` را بلاک کند، تزریق SDK نه `onload` می‌داد نه
   `onerror` → داشبورد **برای همیشه** روی «در حال اتصال…» می‌ماند. حالا
   watchdog سه‌ثانیه‌ای تضمین می‌کند بالا بیاید
3. اگر `charts.js` لود نشود، کل داشبورد می‌مرد → حالا به حالت متنی fallback می‌کند

**تست:** ۶۶ تست پایتون + ۳۰ بررسی رندر واقعی در `tests/ui/`.

### ✅ قدم ۴ فاز ۲ — PM Agent + CRM + Notifications (انجام شد — ۲۰۲۶-۰۸-۲۷)

**PM Agent (§11) — گزارش صبحگاهی با تقویم شمسی:**
- `app/utils/jalali.py` — تبدیل دقیق Gregorian ↔ Jalali با الگوریتم Borkowski (بدون وابستگی خارجی)
  - تست‌شده با تاریخ‌های مرجع jalaali-js: 2023-03-21 = 1402-01-01
  - نام ماه‌ها، روزهای هفته، اعداد فارسی، امروز به وقت تهران
- `app/agents/pm_agent.py` — منطق اولویت‌بندی هوشمند:
  - امتیاز = وزن اولویت (urgent 100 / high 70 / normal 30 / low 10) + وزن وضعیت + معوق/امروز/فردا + سن تسک
  - `prioritized_tasks()` — لیست مرتب با `_priority_score` و تاریخ شمسی موعد
  - `generate_morning_report()` — معوق، امروز، فردا، فوری، صف تأیید، تأییدهای در حال انقضا، پیگیری CRM، سلامت پروژه، velocity
  - `format_morning_report_telegram()` — خروجی Markdown برای تلگرام
  - دستور `/morning` / «گزارش صبحگاهی» + پاپ‌آپ در داشبورد (`/api/morning`)

**CRM پایه (§14):**
- جداول `crm_contacts` (uid, project_id, نام، شرکت، نقش، تلفن، ایمیل، تلگرام، وضعیت، تگ‌ها، یادداشت، منبع، مالک، آخرین تماس)
- `crm_interactions` (uid, contact_id, project_id, نوع call/meeting/message/note/email، خلاصه، محتوا، نتیجه، اقدام بعدی، موعد پیگیری)
- `crm_deals` (uid, contact_id, project_id, عنوان، مبلغ، ارز، مرحله lead/qualified/proposal/negotiation/won/lost، احتمال، موعد بسته شدن)
- `app/crm/repository.py` — CRUD کامل + جستجو + پیگیری‌های پیش رو/معوق + آمار `crm_stats()`
- اتصال به سیستم تأیید (§19): ایجاد 🟢، ویرایش 🟡، حذف مخاطب/معامله 🔴 (دو تأیید)
- اجراکننده‌ها در `app/approvals/actions.py` — ۸ اکشن جدید
- API: `GET/POST /api/crm/contacts`, `GET /api/crm/contacts/<uid>`, `POST/DELETE`, `GET/POST /api/crm/interactions`, `GET/POST /api/crm/deals`, `GET /api/crm/stats`
- دستور `/crm` + تب CRM در داشبورد (۸ تب کل) با شیت ایجاد مخاطب/معامله و شیت جزئیات + پیگیری‌ها

**Notification System (§18):**
- `app/notifications/service.py` — تولید زنده اعلان‌ها از وضعیت DB:
  - تسک معوق (urgent/high = high severity)، موعد امروز/فردا، تسک فوری بدون موعد
  - تأییدهای در حال انقضا (<۲ ساعت) و منقضی‌شده
  - پیگیری CRM معوق و پیش رو (۲ روز آینده)
- جدول `notifications` برای ذخیره اعلان‌های دستی + خوانده/نخوانده
- `GET /api/notifications` — live + persisted + summary
- `POST /api/notifications/<uid>/read` و `/read-all`
- دستور `/notify` + تب اعلان در داشبورد + بج روی تب‌ها + کارت پیش‌نمایش اعلان‌های بحرانی در خلاصه
- به‌روزرسانی `app/miniapp/analytics.py` — `crm` و `notifications` در overview + counts جدید

**تست:** ۱۱۱ تست سبز (۶۶ قبلی + ۲۲ جدید CRM/PM/Notifications/Jalali + ۲۳ Turso).

### ✅ قدم ۵ فاز ۲-۳ — Content Agent + SEO Agent + Automation (انجام شد — ۲۰۲۶-۰۸-۲۷)

**Content Agent (§9):**
- جدول `content_drafts` (uid, topic, title, slug_en, outline, content, FAQ, image_prompt, CTA, meta, word_count, status, cannibalization, seo_score, wordpress_post_id/url)
- `seo_audits` برای ذخیره نتایج بررسی سئو
- `app/content/repository.py` — CRUD + stats
- `app/agents/content_agent.py` — `check_cannibalization()` با Jaccard روی drafts + WordPress `content_index()`، `generate_article()` با LLM ساختاریافته (عنوان فارسی، slug EN، outline، محتوای ۲۰۰۰ کلمه، excerpt، FAQ، image_prompt، CTA، meta_title/description، focus_keyword)
- اتصال به تأیید: `content.draft_create/update` 🟢، `content.generate/publish_draft/delete_draft` 🟡، `content.publish` 🔴
- API: `/api/content/drafts`, `/generate`, `/drafts/<uid>`, `/publish`, `/seo-audit`, `/stats`, `/cannibalization`
- دستور `/content <موضوع>` + تب محتوا (۹ تب) با شیت تولید و جزئیات + SEO audit + انتشار وردپرس

**SEO Agent (§8):**
- `app/agents/seo_agent.py` — `audit_content()` امتیازدهی (طول محتوا، متا title/desc، کلمه کلیدی در عنوان/متا، تراکم، cannibalization risk، FAQ/CTA/image_prompt)
- ذخیره در `seo_audits` + به‌روزرسانی `content_drafts.seo_score`
- دستور `/seo <پروژه>` — گزارش GSC/GA4 + تحلیل محتوا

**Google Search Console + GA4 (§4, §5) — داده واقعی:**
- `app/integrations/google.py` — OAuth refresh → access token، `gsc_query()` با تاریخ پیش‌فرض ۲۸ روز منتهی به ۳ روز قبل (تأخیر GSC)، `gsc_list_sites()`, `gsc_top_queries/pages()`, `ga4_run_report()`, `ga4_realtime_report()`, `get_project_google_data()`
- `app/tools/google_oauth.py` — ابزار CLI یک‌بار برای گرفتن refresh token (مرورگر + localhost callback روی پورت دلخواه)
- بهبود `app/integrations/testers.py` — برای GSC لیست سایت‌ها و بررسی Property، برای GA4 realtime check
- API: `GET /api/google/overview`, `GET /api/projects/<slug>/google`, `GET /api/google/gsc/queries`, `GET /api/google/ga4/report`
- داشبورد: کارت گوگل در خلاصه (کلیک، نمایش، CTR، جایگاه + سشن/کاربر GA4) + بخش گوگل در پرونده پروژه + گزارش صبحگاهی شامل GSC/GA4
- Master Agent: `_action_seo_overview()` با داده واقعی + هشدار اگر اتصال تنظیم نشده

**Automation (§16):**
- `app/automation/cron.py` — `run_morning_job()`, `run_notifications_job()`, `run_daily_jobs()` + تشخیص chat_id از آخرین conversation
- Endpoint امن `GET/POST /internal/cron?secret=CRON_SECRET&job=daily|morning|notifications` در `app/webhook.py`
- `CRON_SECRET` در `config.py` (پیش‌فرض = `WEBHOOK_SECRET`)
- مستند برای `cron-job.org`: هر روز صبح `https://ali-os.onrender.com/internal/cron?secret=...&job=daily`

**تست:** ۱۲۴ تست سبز (۱۱۱ قبلی + ۶ content + ۷ google).

### ✅ قدم ۶ فاز ۳ — Business Analyst + Sales Agent + Financial (بازتعریف) + GSC Charts (انجام شد — ۲۰۲۶-۰۸-۲۷)

**Business Analyst (§12):**
- `app/agents/business_analyst.py` — تحلیل سلامت کسب‌وکار با امتیاز ۰-۱۰۰، ۱۳ نوع insight (معوق، فوری، کاهش سرعت، CRM خالی/معوق، معاملات راکد، نرخ برد، محتوای منتشرنشده، بودجه پرمصرف، صف تأیید شلوغ، پروژه کم‌پیشرفت) + پیشنهاد اقدام
- `GET /api/business/analysis` + کارت در خلاصه داشبورد

**Sales Agent (§13):**
- `app/agents/sales_agent.py` — تحلیل پایپ‌لاین (ارزش کل و وزنی، راکد ۷+ روز، بستن در ۷ روز آینده، پیگیری معوق، اقدام بعدی per stage) + تولید پیام پیگیری فروش با ۳ تون
- `GET /api/sales/pipeline` + کارت در داشبورد

**Financial — درآمد ماهانه (بازتعریف §15 بر اساس نیاز واقعی شما):**
- مشکل قبلی: Financial Agent عمومی (هزینه/درآمد) به کار شما نمی‌آمد — شما گفتی هر پروژه ماهانه مبلغ متفاوت واریز می‌کند و پیگیری واریز مهم‌تر است
- راه‌حل: جدول `project_incomes` با `month_jalali` به صورت `YYYY-MM` (مثلاً ۱۴۰۴-۰۶) + `UNIQUE(project_id, month_jalali)` — هر پروژه در هر ماه شمسی فقط یک رکورد دارد
  - فیلدها: uid, project_id, amount, currency, month_jalali, month_gregorian, due_at (آخر ماه شمسی), paid_at, status (pending/paid/overdue/cancelled/partial), payment_method, transaction_ref, notes
  - `mark_overdue_if_needed()` — خودکار pendingهای گذشته از موعد را overdue می‌کند
  - `monthly_summary()` — ۱۲ ماه اخیر با paid/total/درصد، کل وصولی و نرخ وصول، لیست معوق/در انتظار/ماه جاری
  - `project_contracts_summary()` — میانگین ۳ ماه آخر پرداختی به‌عنوان مبلغ قرارداد تخمینی + وضعیت ماه جاری + تعداد معوق
- API: `GET /api/financial/incomes`, `POST /api/financial/incomes`, `POST /api/financial/incomes/<uid>/paid`, `POST /api/financial/incomes/<uid>` (ویرایش), `DELETE`, `GET /api/financial/summary`
- اجراکننده‌ها: ایجاد/ویرایش/ثبت پرداخت 🟢، حذف 🟡 (نیازمند تأیید)
- دستور `/finance` / `/income` + تب مالی (۱۰ تب کل) با نمودار ۶ ماه اخیر (barList با رنگ سبز/زرد/قرمز بر اساس درصد وصول)، لیست معوق/در انتظار/ماه جاری، قراردادهای فعال
- ادغام با Business Analyst — اگر واریز معوق باشد، insight و پیشنهاد «پیگیری واریز» می‌دهد
- قابل توسعه: می‌توان بعداً ستون‌های `recurring` (ماهیانه خودکار)، `auto_create_next_month`، `discount`, `tax` اضافه کرد

**Monitoring / Analytics — GSC Charts (بازتعریف بر اساس پیشنهاد شما):**
- مشکل قبلی: پینگ مداوم سایت (Monitoring Agent کلاسیک) منابع مصرف می‌کند و باگ می‌اندازد
- پیشنهاد شما: به‌جای آپتایم، نمودار Search Console + Analytics با داده واقعی + پیشنهادهای دستیار بر اساس آن
- راه‌حل:
  - `app/integrations/google.py` — اضافه شدن `gsc_daily_trend()` (dimensions=["date"]), `gsc_device_breakdown()`, `gsc_country_breakdown()`, `ga4_daily_trend()` (dimensions=["date"])
  - باگ فیکس: `dimensions or ["query"]` → `dimensions if dimensions is not None else ["query"]` تا `dimensions=[]` برای آمار کلی کار کند
  - `app/integrations/gsc_storage.py` — ذخیره تاریخچه روزانه در `gsc_daily_stats` و `ga4_daily_stats` با `ON CONFLICT DO UPDATE` — کم‌مصرف، بدون کرون مداوم، فقط وقتی `POST /api/google/sync` صدا زده می‌شود یا در `get_project_google_data()` (که daily را هم می‌گیرد)
  - جداول `gsc_daily_stats` و `ga4_daily_stats` با `date` و `date_jalali` + queries/pages JSON + ایندکس‌ها
  - API: `POST /api/google/sync` — همگام‌سازی ۲۸ روز اخیر به storage (برای نمودار بدون فشار به API)
  - داشبورد: کارت گوگل در خلاصه حالا نمودار خطی ۲۸ روزه کلیک/نمایش (SVG)، تفکیک دستگاه (DESKTOP/MOBILE/TABLET)، کوئری‌ها و صفحات برتر + دکمه «💾 ذخیره تاریخچه»
  - پرونده پروژه: بخش گوگل با آمار کلی + کوئری‌های برتر (async)
  - `analytics.py`: `gsc_trend_overview()` از storage + `financial_overview()` + business/sales — همه در `/api/analytics` یکجا
  - این مدل هم کم‌مصرف است (فقط وقتی کاربر بخواهد sync می‌کند یا از cache) و هم داده واقعی برای پیشنهادهای Business Analyst می‌دهد

**تست:** ۱۳۸ تست سبز (۱۲۴ قبلی + ۷ financial + ۷ business_sales).

> قدم بعدی فاز ۳-۴: Content Agent پیشنهاد موضوع از GSC (کوئری‌های با ایمپرشن بالا و CTR پایین) + Monitoring سبک فقط برای GSC/GA4 (بدون پینگ مداوم) + Sales Agent اتصال به تلگرام برای ارسال پیام پیگیری.





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
