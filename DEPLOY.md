# استقرار Ali OS روی Render (رایگان، بدون کارت بانکی)

این راهنما Ali OS را روی پلن رایگان **Render** بالا می‌آورد.
دیتابیس روی **Turso** قرار دارد که قبلاً ساختیم و schema آن آماده است.

> ⏱ پلن رایگان Render بعد از ۱۵ دقیقه بی‌کاری می‌خوابد و با اولین درخواست بعدی دوباره بیدار می‌شود (چند ثانیه تأخیر). Mini App خودش retry می‌کند و تلگرام هم پیام را دوباره می‌فرستد.

---

## گام ۱ — ساخت ریپازیتوری GitHub

۱. در [github.com](https://github.com) یک ریپو جدید بساز (مثلاً `ali-os`، Private یا Public فرقی نمی‌کند).
۲. فایل `ali-os.zip` که در workspace است را دانلود و از حالت فشرده خارج کن.
۳. همه‌ی فایل‌های داخلش را در ریشه‌ی ریپو آپلود کن (یا با `git push`).
   - `.env` و پوشه‌ی `data/` عمداً داخل zip نیستند (امنیت).
   - فایل `render.yaml` در ریشه قرار دارد که Render خودکار می‌خواندش.

---

## گام ۲ — ساخت سرویس روی Render

۱. در [dashboard.render.com](https://dashboard.render.com) با GitHub لاگین کن (رایگان، بدون کارت).
۲. **New +** → **Blueprint** را بزن.
۳. ریپوی `ali-os` را انتخاب کن و **Connect** بزن.
۴. Render فایل `render.yaml` را می‌خواند و ازت می‌خواهد مقادیر Secret را وارد کنی.

---

## گام ۳ — وارد کردن Environment Variables

این مقادیر را در کادرهای Blueprint وارد کن:

| کلید | مقدار |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `8619491353:AAHBXZ6kOVcVFLpR9pc8dr-OszyP95HGHQ4` |
| `WEBHOOK_SECRET` | `ali_os_wh_9f3a7c2e8b1d` |
| `LLM_API_KEY` | کلید API مدل (`dahl_E7WfdWXaKf35yQxGdHY5mq5sjfuUANSmn`) |
| `TURSO_DATABASE_URL` | `libsql://ali-os-aliterojan75-coder.aws-ap-northeast-1.turso.io` |
| `TURSO_AUTH_TOKEN` | توکن خواندن/نوشتن Turso که ساختی |
| `ENCRYPTION_KEY` | کلید رمزنگاری اطلاعات اتصال‌ها — با `python -m app.tools.gen_key` بساز |

> ⚠️ **درباره‌ی `ENCRYPTION_KEY`:** این کلید رمزهای وردپرس/گوگل/SMTP را رمزنگاری می‌کند.
> تا وقتی ست نشود، Ali OS عمداً از ذخیره‌ی هر اطلاعات محرمانه‌ای خودداری می‌کند
> (به‌جای اینکه آن را بدون رمز ذخیره کند). اگر بعداً این کلید را عوض کنی،
> اتصال‌های ذخیره‌شده‌ی قبلی قابل خواندن نیستند و باید دوباره وارد شوند.
> این کلید را جایی امن نگه دار و هرگز در گیت نگذار.

مقادیر زیر از قبل در `render.yaml` ست شده‌اند و لازم نیست کاری کنی:
- `LLM_BASE_URL=https://inference.dahl.global/v1`
- `LLM_MODEL=MiniMaxAI/MiniMax-M2.7`
- `AUTO_SET_WEBHOOK=1`
- `FLASK_ENV=production`

۵. **Apply** / **Deploy** را بزن.

---

## گام ۴ — منتظر بمان تا Build تمام شود

Render بعد از ۲ تا ۵ دقیقه:
- پکیج‌ها را نصب می‌کند،
- سرور گانیکورن را بالا می‌آورد،
- در استارت‌آپ خودش به Turso وصل می‌شود،
- webhook تلگرام و دکمه‌ی **Mini App** را روی آدرس سرویس تنظیم می‌کند
  (آدرس Render به‌صورت خودکار به‌عنوان `RENDER_EXTERNAL_URL` خوانده می‌شود، نیازی به ست کردن `PUBLIC_URL` نیست).

آدرس سرویس تو چیزی شبیه این می‌شود:
```
https://ali-os.onrender.com
```

---

## گام ۵ — تست

- باز کن: `https://<آدرس سرویس>/health`
  باید ببینی: `{"ok": true, "service": "ali-os", ...}`
- در تلگرام برای بات `/start` بفرست.
- دکمه‌ی منوی پایین چت، **داشبورد Ali OS** را باز می‌کند.

---

## اگر خواستی به‌جای Blueprint، دستی سرویس بسازی

**New + → Web Service → GitHub → ریپو** و این تنظیمات:

- **Runtime:** Python 3
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:**
  ```
  gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
  ```
- **Instance Type:** Free
- **Health Check Path:** `/health`
- همان ۵ متغیر محیطی بالا را اضافه کن.

---

## نکات

- **Cold start:** اولین درخواست بعد از بی‌کاری ۲۰ تا ۴۰ ثانیه طول می‌کشد. اپ داشبورد خودش تلاش مجدد می‌کند.
- **ماندگاری داده:** همه‌ی Task/پروژه/حافظه در Turso ذخیره می‌شوند و با ری‌استارت Render پاک نمی‌شوند.
- **امنیت:** هیچ secret در کد نیست. توکن‌ها فقط در Environment Variables تنظیم می‌شوند.
- **بروزرسانی:** هر بار که روی branch اصلی GitHub پوش کنی، Render خودکار دیپلوی می‌کند.
