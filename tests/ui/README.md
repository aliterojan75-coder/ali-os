# تست‌های رابط کاربری (headless)

این تست‌ها داشبورد واقعی را در jsdom بالا می‌آورند و بررسی می‌کنند که نمودارها
با داده‌ی واقعی رندر می‌شوند — نه فقط اینکه سینتکس JS درست است.

```bash
# ۱) سرور را با داده‌ی نمونه بالا بیاور
DATABASE_PATH=/tmp/demo.db ENCRYPTION_KEY=dev-key \
  TELEGRAM_BOT_TOKEN=demo LLM_API_KEY=demo AUTO_SET_WEBHOOK=0 FLASK_ENV=development \
  python -m flask --app wsgi:app run --port 8080

# ۲) تست‌ها
npm install jsdom
node tests/ui/dashboard.test.mjs   # ۳۰ بررسی: چارت‌ها، تب‌ها، پرونده پروژه
node tests/ui/fallback.test.mjs    # داشبورد بدون charts.js هم باید کار کند
```

`dashboard.test.mjs` عمداً از مسیر واقعی boot عبور می‌کند (نه صدا زدن دستی
`init()`)، چون همین مسیر بود که دو باگ واقعی را لو داد:
DOM-readiness و هنگ‌کردن روی شبکه‌ای که `telegram.org` را بلاک می‌کند.
