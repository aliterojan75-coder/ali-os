# بکاپ و بازیابی دیتابیس (P1)

## خودکارسازی شبانه
Workflow هر شب (~۰۶:۰۰ تهران) یک اسنپ‌شات SQLite سالم از Turso می‌گیرد و به‌عنوان
**Artifact** (نگهداری ۳۰ روز) آپلود می‌کند.

**نصب (۶۰ ثانیه):** دسترسی GitHub App در این سشن اجازه ایجاد فایل workflow ندارد —
این فایل را دستی بساز: `Actions → New workflow → set up a workflow yourself` و
محتوای زیر را در `nightly-backup.yml` پیست کن (اسکریپت `scripts/turso_backup.py`
داخل ریپو موجود است):

```yaml
name: Nightly Turso backup

# P1 — free-tier insurance for CRM/financial data. ~06:00 Tehran time.
on:
  schedule:
    - cron: "30 2 * * *"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install --quiet libsql-client
      - name: Snapshot Turso → SQLite
        run: python scripts/turso_backup.py --out backup/ali_os_snapshot.sqlite
        env:
          TURSO_DATABASE_URL: ${{ secrets.TURSO_DATABASE_URL }}
          TURSO_AUTH_TOKEN: ${{ secrets.TURSO_AUTH_TOKEN }}
      - uses: actions/upload-artifact@v4
        with:
          name: ali-os-db-${{ github.run_id }}
          path: backup/ali_os_snapshot.sqlite
          retention-days: 30
          if-no-files-found: error
```

یک‌بار تنظیم کن:

1. Render → Service ali-os → Environment → مقادیر `TURSO_DATABASE_URL` و `TURSO_AUTH_TOKEN` را کپی کن.
2. GitHub → repo → Settings → Secrets and variables → Actions →
   `New repository secret` با همان دو نام.
3. از تب Actions دستی «Run workflow» بزن و لاگ را ببین: `backup ok @ ...`.

> اگر secretها ست نشده باشند workflow فیل می‌شود — عمداً؛ بکاپ بی‌هشدار نگه‌دار.

## دستی

```bash
TURSO_DATABASE_URL=libsql://... TURSO_AUTH_TOKEN=... python scripts/turso_backup.py
```

## بازیابی

- **مرور داده‌ها:** artifact را دانلود کن و مستقیم با اپ محلی اجرا کن —
  `DATABASE_PATH=ali_os_snapshot.sqlite gunicorn wsgi:app` (اپ از SQLite لوکال پشتیبانی می‌کند).
- **بازگشت کامل به سرویس:** یک Turso DB جدید بساز، snapshot را با
  `sqlite3` به `.sql` dump تبدیل و import کن؛ سپس `TURSO_DATABASE_URL` را در Render عوض کن.
  (پلن رایگانTurso، `turso db create --from-file` را در CLI پشتیبانی می‌کند — ابتدا `turso db shell` را تست کن.)

## چرا ۳۰ روز؟
بیشترین نیاز عملی «دیروز چه شد» است؛ برای آرشیو بلندمدت، retention را در
workflow بالا ببر یا artifactها را به Object Storage منتقل کن.
