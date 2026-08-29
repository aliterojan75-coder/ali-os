# Ali OS — Personal AI Operating System

یک **Master AI Agent** که از طریق تلگرام کنترل می‌شود. تلگرام فقط رابط (Interface) است؛ مغز واقعی در Backend قرار دارد.

```
Telegram → Webhook → Flask/Gunicorn → Master Agent → LLM + Memory + Tasks
```

## وضعیت فعلی (MVP — Phase 1)
- ✅ اعتبارسنجی API مدل و توکن تلگرام
- ✅ **LLM Adapter** تمیز با رابط `LLMProvider` (OpenAI-compatible؛ پیش‌فرض Gemini API)
- ✅ جداکننده‌ی تگ `<think>` از پاسخ نهایی
- ✅ Webhook تلگرام با احراز هویت `secret_token`
- ✅ Master Agent پایه با Intent Router
- ✅ Memory لایه‌بندی‌شده (SQLite، قابل مهاجرت به PostgreSQL)
- ✅ Project / Task / Decision / Event schema
- ✅ Seed پروژه‌های واقعی (Net Nova، گیاهکده، E-Ferdowsی، امداد سرویس قم، CropExport، آبادگران، Sir-Siah)
- ✅ ثبت Task از زبان طبیعی، لیست Task، وضعیت پروژه، آخرین تصمیم
- ✅ Event Log
- ✅ **Telegram Mini App — پنل مدیریت (RTL، موبایل‌محور):**
  - آمار، پروژه‌ها، تسک‌ها، تصمیم‌ها، حافظه، لاگ رویدادها
  - ساخت و تغییر وضعیت تسک از داخل داشبورد
  - احراز هویت با امضای HMAC رسمی تلگرام (`initData`)
  - باز شدن از دکمه منوی بات (Menu Button)

## Phase 2 — در حال ساخت
- ✅ **Approval System سه‌سطحی (§19)** — 🟢 اجرای مستقیم، 🟡 یک تأیید، 🔴 تأیید دو مرحله‌ای
  - جدول `pending_actions` + دکمه‌های Inline تلگرام `[✅ تأیید] [❌ لغو]` + هندل `callback_query`
  - هیچ Agentی بدون رکورد تأییدشده عملیات 🟡/🔴 اجرا نمی‌کند
  - کارت تأیید بعد از تصمیم قفل می‌شود → audit trail داخل خود چت
  - دستور `/approvals` برای دیدن صف تأیید
  - 📖 مستند کامل: [`docs/APPROVALS.md`](docs/APPROVALS.md)
- ✅ **پرونده‌ی کامل پروژه (§2)** — KPI، بودجه، افراد + Task/تصمیم/حافظه/تأییدهای باز
  - دستور `/dossier <پروژه>` یا «پرونده گیاهکده»
  - `GET /api/projects/<slug>/dossier`
- ✅ **اتصال‌ها / مدیریت Secret (§20)** — ورودی‌ها را از داخل خود اپ می‌گیرد
  - تب «🔌 اتصال‌ها» در داشبورد: فرم‌ها از روی کاتالوگ سرویس‌ها خودکار ساخته می‌شوند
  - رمزنگاری Fernet روی credentialها؛ API فقط مقدار ماسک‌شده برمی‌گرداند
  - **تست زنده‌ی اتصال** بلافاصله بعد از ذخیره (وردپرس، کانال تلگرام، SMTP، OAuth گوگل)
  - سرویس‌های مسدود (Google Ads/GBP/Instagram) با دلیل روشن نمایش داده می‌شوند
  - دستور `/connections` + 📖 [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)
- ✅ **WordPress Agent (§3)** — پیش‌نویس/ویرایش 🟡، انتشار/حذف 🔴، فیلدهای Rank Math،
  و `content_index()` برای جلوگیری از Cannibalization
- ✅ **بازطراحی کامل داشبورد (UI/UX)** — نمودار، انیمیشن، و ناوبری ۸ تبی
  - نمودار خطی روند ۱۴ روزه (ایجاد در برابر انجام)، دونات وضعیت، گیج KPI،
    نوار اولویت، هیت‌مپ فعالیت ۸ هفته، نوار انباشته‌ی تأییدها
  - **همه‌ی نمودارها SVG درون‌خطی‌اند — بدون CDN و بدون کتابخانه‌ی بیرونی**،
    چون داشبورد باید روی شبکه‌هایی که CDN را بلاک می‌کنند هم کامل بالا بیاید
  - اسکلت لودینگ، بازخورد لمسی (Haptic)، شیت پرونده‌ی پروژه، بج شمارنده روی تب تأیید
  - اعداد فارسی در کل رابط، RTL کامل، احترام به `prefers-reduced-motion`
  - ۸ تب: خلاصه / تسک‌ها / پروژه‌ها / CRM / تأیید / اعلان / اتصال / بیشتر
- ✅ **PM Agent (§11)** — گزارش صبحگاهی با تقویم شمسی
  - تبدیل تاریخ شمسی دقیق (الگوریتم Borkowski — بدون وابستگی خارجی)
  - اولویت‌بندی هوشمند تسک‌ها: امتیازدهی بر اساس فوریت، موعد، معوق بودن، پروژه
  - گزارش صبحگاهی شامل: تسک‌های معوق، امروز/فردا، فوری، صف تأیید، پیگیری CRM، سرعت تیم
  - دستور `/morning` در تلگرام + پاپ‌آپ گزارش در داشبورد + `GET /api/morning`
  - `GET /api/pm/prioritized` — لیست تسک‌های مرتب‌شده با امتیاز
- ✅ **CRM پایه (§14)** — مخاطبان، تعاملات، معاملات
  - جداول `crm_contacts` / `crm_interactions` / `crm_deals` + ایندکس‌های بهینه
  - وضعیت‌ها: سرنخ/مشتری بالقوه/مشتری/شریک/آرشیو + مراحل معامله (۶ مرحله)
  - پیگیری‌ها با `next_follow_up_at` و تشخیص معوق/پیش رو
  - اتصال به سیستم تأیید: ایجاد 🟢، ویرایش 🟡، حذف 🔴
  - دستور `/crm` + API کامل `/api/crm/*` + تب CRM در داشبورد با شیت جزئیات
- ✅ **Notification System (§18)** — پایش خودکار
  - تسک‌های معوق، موعد امروز/فردا، تسک‌های فوری، تأییدهای در حال انقضا/منقضی، پیگیری CRM
  - تولید زنده (بدون نیاز به Cron) + جدول `notifications` برای ذخیره خوانده/نخوانده
  - دستور `/notify` + `GET /api/notifications` + بج روی تب اعلان + کارت پیش‌نمایش در خلاصه
  - `POST /api/notifications/read-all` برای علامت‌گذاری خوانده‌شده
- ✅ **Content Agent (§9)** — تولید مقاله با سئو و جلوگیری از Cannibalization
  - جدول `content_drafts` + `seo_audits` + بررسی مشابهت Jaccard روی drafts و WordPress `content_index`
  - تولید با LLM: عنوان فارسی، slug انگلیسی، outline، محتوای ۲۰۰۰ کلمه‌ای، چکیده، FAQ، image_prompt، CTA، meta_title/description، focus_keyword
  - اتصال به تأیید: تولید 🟡، پیش‌نویس وردپرس 🟡، انتشار نهایی 🔴
  - دستور `/content <موضوع>` + API `/api/content/*` + تب محتوا در داشبورد (۹ تب)
- ✅ **SEO Agent (§8)** — تحلیل on-page
  - امتیازدهی: طول محتوا، متا، کلمه کلیدی، تراکم، cannibalization، FAQ/CTA
  - دستور `/seo <پروژه>` + `POST /api/content/drafts/<uid>/seo-audit`
- ✅ **Google Search Console + GA4 (§4, §5)** — داده واقعی با نمودار
  - `app/integrations/google.py`: OAuth refresh → access token، `searchanalytics.query` و GA4 `runReport`/`runRealtimeReport` + `gsc_daily_trend`, `gsc_device_breakdown`, `ga4_daily_trend`
  - `app/integrations/gsc_storage.py`: ذخیره تاریخچه روزانه GSC/GA4 برای نمودار بدون فشار به API (کم‌مصرف، بدون باگ منابع)
  - `app/tools/google_oauth.py`: ابزار یک‌بار برای گرفتن refresh token (مرورگر + localhost callback)
  - تست اتصال بهبودیافته: لیست سایت‌ها و بررسی Property
  - `GET /api/projects/<slug>/google` و `/api/google/overview` + `/gsc/queries` + `/ga4/report` + `POST /api/google/sync` برای ذخیره تاریخچه
  - کارت گوگل در خلاصه داشبورد با نمودار خطی روند ۲۸ روزه کلیک/نمایش + تفکیک دستگاه + کوئری‌ها و صفحات برتر + بخش گوگل در پرونده پروژه + گزارش صبحگاهی شامل GSC/GA4
  - دستور `/seo` شامل داده واقعی GSC/GA4
- ✅ **Automation (§16)** — گزارش صبحگاهی خودکار
  - `app/automation/cron.py` + endpoint امن `/internal/cron?secret=...&job=daily|morning|notifications`
  - برای `cron-job.org` یا GitHub Actions
- ✅ **Business Analyst (§12)** — تحلیل سلامت کسب‌وکار
  - امتیاز سلامت ۰-۱۰۰، یافته‌ها (معوق، سرعت، CRM، معاملات راکد، نرخ برد، بودجه) + پیشنهاد اقدام
  - دستور `/business` + API `/api/business/analysis` + کارت در داشبورد
- ✅ **Sales Agent (§13)** — پایپ‌لاین فروش
  - ارزش Pipeline و وزنی، راکد، بستن زودهنگام، اقدام بعدی، تولید پیام پیگیری فروش
  - دستور `/sales` + API `/api/sales/*` + کارت در داشبورد
- ✅ **Financial — درآمد ماهانه (بازتعریف §15)** — پیگیری واریز پروژه‌ها
  - جدول `project_incomes` با ماه شمسی `YYYY-MM`، مبلغ، وضعیت `pending/paid/overdue`، روش پرداخت، شماره تراکنش
  - هر پروژه فقط یک رکورد در هر ماه شمسی (UNIQUE) — دقیقاً مدل کاری شما: هر پروژه ماهانه مبلغ متفاوت واریز می‌کند
  - `monthly_summary()` — ۱۲ ماه اخیر، نرخ وصول، معوقات، ماه جاری + `project_contracts_summary()` — میانگین قرارداد ۳ ماه آخر + وضعیت ماه جاری
  - اتصال به تأیید: ایجاد/ویرایش/ثبت پرداخت 🟢، حذف 🟡
  - دستور `/finance` / `/income` + API `/api/financial/*` + تب مالی (۱۰ تب کل) با نمودار ۶ ماه اخیر، لیست معوق/در انتظار، قراردادهای فعال
  - ادغام با Business Analyst — تحلیل درآمد و پیشنهاد پیگیری واریزهای معوق
- ⬜ Monitoring Agent سبک (فقط GSC/GA4 charts — بدون پینگ مداوم که منابع مصرف کند)

## فاز ۴ — امنیت، سرعت و بلوغ (در حال اجرا — ۲۰۲۶-۰۸-۲۷)
- ✅ **P0 — فیلتر مالکیت بات**: با تنظیم `TELEGRAM_ADMIN_CHAT_ID` بات فقط به چت‌های مجاز
  پاسخ می‌دهد؛ ناشناس‌ها یک رد مؤدبانه (هروقت یک‌بار) می‌گیرند و در event log ثبت می‌شوند.
  دکمه‌های تأیید هم مالک-محور شدند. برای پیدا کردن chat id خودت: `/whoami`.
- ✅ **سرعت پنل** — سه گلوگاه کُندکننده حذف شد:
  ۱) توکن OAuth گوگل و داده GSC/GA4 حالا کش ۵۵/۳۰ دقیقه‌ای دارند (داده GSC ذاتاً ۲-۳ روز تأخیر دارد — هر رندر = ۱۰ فراخوانی هم‌زمان گوگل، روی ۱ worker فاجعه بود). sync دستی = `?fresh=1`.
  ۲) **gzip** روی HTML/JSON/SVG — انتقال داشبورد ~۴× کوچک‌تر.
  ۳) بلوک تکراری ۶۰۰ خطی JS داشبورد (میراث PR #4 که با `let` تکراری عملاً اسکریپت را می‌کشت) حذف شد؛ `loadGoogleCharts` هم از snapshot موجود استفاده می‌کند نه fetch دوم.
- ✅ **P2 — Sales → تلگرام مخاطب**: «پیگیری بده» در تلگرام یا `POST /api/sales/send-followup` —
  پیش‌نمایش، کارت تأیید 🟡، ارسال، لاگ در `crm_interactions`.
- ✅ **P3 — صفحات در حال مرگ**: مقایسه ۲۸ روز اخیر با قبلش از `gsc_daily_stats`؛ کارت جدید در
  پنل گوگل + دکمه «بازنویسی» که مستقیم شیت تولید محتوا را با موضوع باز می‌کند.
  (sync الان pages/queries روزانه را هم ذخیره می‌کند — منبع همین تحلیل و P5.)
- ✅ **P5 (زیرساخت)** — `gsc_cannibalization()`: یک کوئری واقعی GSC با dimensions=(query,page)
  که کوئری‌های رقابت‌کننده بین چند صفحه را بیرون می‌کشد.
- ✅ **P1 — بکاپ شبانه**: `nightly-backup.yml` (Turso → SQLite snapshot، integrity check،
  Artifact ۳۰ روزه). 📖 [`docs/BACKUP.md`](docs/BACKUP.md) — دو secret لازم در GitHub.

## دستورات تلگرام
| دستور | کار |
|-------|-----|
| `/start` | معرفی و راهنما |
| `/tasks` یا «کارها» | Taskهای باز |
| `/approvals` | صف اقدامات در انتظار تأیید |
| `/dossier <پروژه>` | پرونده‌ی کامل پروژه |
| `/connections` | وضعیت اتصال‌ها (وردپرس، گوگل، تلگرام…) |
| `/morning` | گزارش صبحگاهی با تقویم شمسی و اولویت‌بندی هوشمند |
| `/crm` | مخاطبان و معاملات CRM + پیگیری‌ها |
| `/notify` | اعلان‌ها — تسک معوق، تأیید در حال انقضا، CRM |
| `/content <موضوع>` | تولید مقاله با سئو و Cannibalization چک |
| `/seo <پروژه>` | وضعیت سئو — Search Console + GA4 + تحلیل محتوا + نمودار |
| `/business` | تحلیل سلامت کسب‌وکار، یافته‌ها و پیشنهاد اقدام |
| `/sales` | پایپ‌لاین فروش، راکد، بستن زودهنگام، پیام پیگیری |
| `/finance` یا `/income` | درآمد ماهانه پروژه‌ها — واریزی‌ها، معوقات، نرخ وصول |
| `/whoami` | شناسه چت تلگرام تو (لازم برای `TELEGRAM_ADMIN_CHAT_ID`) |

بقیه‌ی تعامل زبان طبیعی است؛ Intent Router خودش تشخیص می‌دهد.

## تست

```bash
python -m pytest tests -q      # ۱۵۸ تست پایتون — بدون شبکه، بدون تلگرام واقعی

# تست رابط کاربری (نیازمند سرور در حال اجرا + npm install jsdom)
node tests/ui/dashboard.test.mjs   # ۳۰ بررسی رندر واقعی نمودارها
node tests/ui/fallback.test.mjs    # داشبورد بدون charts.js هم باید کار کند
```

## LLM / Gemini

- Provider پیش‌فرض `OpenAICompatibleProvider` است و با Gemini API از مسیر سازگاری OpenAI کار می‌کند.
- در Render مقدارهای ثابت: `LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai` و `LLM_MODEL=gemini-3.7-flash`؛ فقط `LLM_API_KEY` را دستی در Render ست کن (`sync:false`).
- تست curl و تست structured output زنده در [`docs/LLM.md`](docs/LLM.md) آمده است.
- اگر مدل/endpoint خطای موقت بدهد، آداپتور retry/backoff و fallback اختیاری دارد و چت تلگرام به‌جای crash پیام فارسی «مدل موقتاً نیست، دستورهای داده‌محور کار می‌کنند» می‌دهد.

## پنل مدیریت (Mini App)
- مسیر: `GET /` (یا `/app`) → SPA
- API: `GET/POST /api/*` با هدر `X-Telegram-Init-Data`
- ابزارها:
  - `python -m app.tools.set_webhook`
  - `python -m app.tools.set_menu` (دکمه منوی Mini App + ثبت دستورات `/`)
  - `python -m app.tools.gen_key` (ساخت `ENCRYPTION_KEY` برای اتصال‌ها — یک‌بار)

## اجرا

```bash
pip install -r requirements.txt

# تنظیم env در .env
cp .env .env  # فایل از قبل ساخته شده

# 1) راه‌اندازی DB و seed
python -m app.seed

# 2) اجرای سرور
gunicorn wsgi:app --bind 0.0.0.0:8080 --workers 1 --threads 4
```

برای اتصال webhook تلگرام، در `.env` مقدار `PUBLIC_URL` را روی HTTPS آدرس سرور بگذار و سرور را ری‌استارت کن (یا به‌صورت دستی):
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<PUBLIC_URL>/webhook&secret_token=ali_os_wh_9f3a7c2e8b1d"
```

## عیب‌یابی: Mini App با «پروکسی تلگرام» باز نمی‌شود

- **پروکسی تلگرام (MTProto) فقط ترافیک خودِ تلگرام را تونل می‌کند.** وب‌ویوی Mini App یک صفحه‌ی وب معمولی از `ali-os.onrender.com` است که از این پروکسی رد نمی‌شود؛ بنابراین با فقط پروکسیِ داخل تلگرام، پنل فقط وقتی بالا می‌آید که اینترنت دستگاه مستقلاً به آن آدرس دسترسی داشته باشد. برای باز شدن مطمئن، کل اینترنت دستگاه (فیلترشکن) باید فعال باشد — این محدودیت تلگرام است، نه باگ کد.
- **Cold-start هاست رایگان:** بعد از ~۱۵ دقیقه بی‌ترافیکی، سرویس می‌خوابد و اولین درخواست ۳۰–۶۰ ثانیه طول می‌کشد (گاهی Render با کد 200 یک صفحه‌ی HTML «Application loading» برمی‌گرداند؛ فرانت‌اند این حالت را تشخیص می‌دهد و retry می‌کند). برای بیدار ماندن، یک uptime-pinger رایگان (مثل UptimeRobot) روی `/health` بگذار.
- **بدون وابستگی خارجی:** فونت به‌صورت غیرمسدودکننده لود می‌شود و SDK تلگرام هم وقتی کلاینت خودش تزریق کرده باشد، هیچ درخواستی به `telegram.org` (که در ایران فیلتر است) زده نمی‌شود؛ تنها میزبان لازم برای پنل، خود دامنه‌ی سرویس است.


## ساختار
```
ali-os/
├── app/
│   ├── webhook.py          # Flask + /webhook + /health
│   ├── config.py
│   ├── logging_config.py
│   ├── db.py               # SQLite + schema
│   ├── repositories.py     # دسترسی به داده‌ها
│   ├── seed.py             # پروژه‌ها و حافظه اولیه
│   ├── llm/
│   │   ├── base.py         # LLMProvider (chat/stream/structured_output/model_info/health_check)
│   │   └── openai_compatible.py # آداپتور عمومی OpenAI-compatible (Gemini/Groq/…)
│   ├── master/
│   │   ├── agent.py        # Orchestrator
│   │   └── prompts.py
│   └── telegram/
│       └── client.py
├── wsgi.py
├── requirements.txt
└── .env
```

## اصول
- هیچ Secret در کد نیست؛ همه از Environment خوانده می‌شوند.
- LLM Provider از Business Logic جدا است؛ پیش‌فرض فعلی Gemini از مسیر OpenAI-compatible است. راهنمای تست: [`docs/LLM.md`](docs/LLM.md).
- Request layer **stateless** است؛ همه‌چیز در DB پایدار می‌شود.
- برای کارهای مهم: Claim → Evidence → Reasoning → Decision → Action → Result.
