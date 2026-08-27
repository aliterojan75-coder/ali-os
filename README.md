# Ali OS — Personal AI Operating System

یک **Master AI Agent** که از طریق تلگرام کنترل می‌شود. تلگرام فقط رابط (Interface) است؛ مغز واقعی در Backend قرار دارد.

```
Telegram → Webhook → Flask/Gunicorn → Master Agent → LLM + Memory + Tasks
```

## وضعیت فعلی (MVP — Phase 1)
- ✅ اعتبارسنجی API مدل و توکن تلگرام
- ✅ **LLM Adapter** تمیز با رابط `LLMProvider` (OpenAI-compatible روی Dahl / MiniMax-M2.7)
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
- ⬜ Content Agent (قدم بعدی)

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

بقیه‌ی تعامل زبان طبیعی است؛ Intent Router خودش تشخیص می‌دهد.

## تست

```bash
python -m pytest tests -q      # ۱۱۱ تست پایتون — بدون شبکه، بدون تلگرام واقعی

# تست رابط کاربری (نیازمند سرور در حال اجرا + npm install jsdom)
node tests/ui/dashboard.test.mjs   # ۳۰ بررسی رندر واقعی نمودارها
node tests/ui/fallback.test.mjs    # داشبورد بدون charts.js هم باید کار کند
```

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
│   │   └── minimax_dahl.py # آداپتور MiniMax-M2.7
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
- LLM Provider از Business Logic جدا است (قابل تعویض با Kimi/OpenAI/Claude).
- Request layer **stateless** است؛ همه‌چیز در DB پایدار می‌شود.
- برای کارهای مهم: Claim → Evidence → Reasoning → Decision → Action → Result.
