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

## پنل مدیریت (Mini App)
- مسیر: `GET /` (یا `/app`) → SPA
- API: `GET/POST /api/*` با هدر `X-Telegram-Init-Data`
- ابزارها:
  - `python -m app.tools.set_webhook`
  - `python -m app.tools.set_menu` (دکمه منوی Mini App)

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
