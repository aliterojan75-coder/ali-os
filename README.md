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
- ⬜ CRM پایه، WordPress Agent، PM Agent، جدول `integrations`

## دستورات تلگرام
| دستور | کار |
|-------|-----|
| `/start` | معرفی و راهنما |
| `/tasks` یا «کارها» | Taskهای باز |
| `/approvals` | صف اقدامات در انتظار تأیید |
| `/dossier <پروژه>` | پرونده‌ی کامل پروژه |

بقیه‌ی تعامل زبان طبیعی است؛ Intent Router خودش تشخیص می‌دهد.

## تست

```bash
python -m pytest tests -q      # ۲۴ تست — بدون شبکه، بدون تلگرام واقعی
```

## پنل مدیریت (Mini App)
- مسیر: `GET /` (یا `/app`) → SPA
- API: `GET/POST /api/*` با هدر `X-Telegram-Init-Data`
- ابزارها:
  - `python -m app.tools.set_webhook`
  - `python -m app.tools.set_menu` (دکمه منوی Mini App + ثبت دستورات `/`)

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
